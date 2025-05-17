import requests
import time
import asyncio
import platform
from typing import Optional
from threading import Thread
from dotenv import load_dotenv
import os

load_dotenv()

from pipecat.frames.frames import AudioRawFrame, TextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.local.audio import LocalAudioTransport,LocalAudioTransportParams
from pipecat.processors.frame_processor import FrameProcessor


class CustomPipelineRunner(PipelineRunner):
    def __init__(self):
        super().__init__()
        self._task: Optional[PipelineTask] = None

    def _setup_sigint(self):
        
        if platform.system() != "Windows":
            super()._setup_sigint()



patient_profile = {
    "patient_id": "CL-P00123",
    "full_name": "Mrs. Kavita Sharma",
    "date_of_birth": "1980-08-12",
    "high_risk_symptoms_to_check": [
        "Fever ≥38 °C (100.4 °F)",
        "Severe vomiting (≥4 episodes in 24 h or unable to keep liquids down)",
        "Shortness of breath or chest tightness"
    ],
    "next_followup_visit": "2025-05-20"
}


ALERT_API_URL = "http://localhost:5000/alert"


class CustomNLUProcessor(FrameProcessor):
    async def process_frame(self, frame, direction):
        if isinstance(frame, TextFrame):
            text = frame.text.lower()
            # Basic Hinglish understanding
            if "haan" in text or "yes" in text:
                return TextFrame("yes")
            elif "nahi" in text or "no" in text:
                return TextFrame("no")
            return frame
        return frame


class DialogueManager:
    def __init__(self, patient_profile):
        self.state = "INIT"
        self.patient_profile = patient_profile
        self.verified = False
        self.symptom_index = 0
        self.high_risk_detected = False

    async def process_frame(self, frame):
        if isinstance(frame, TextFrame):
            user_input = frame.text
            response = self.process(user_input)
            return TextFrame(response)
        return frame

    def process(self, user_input):
        if self.state == "INIT":
            self.state = "VERIFY_NAME"
            return "Namaste, main aapka healthcare agent hoon. Kya aap Mrs. Kavita Sharma hain?"
        elif self.state == "VERIFY_NAME":
            if user_input.lower() == self.patient_profile["full_name"].lower():
                self.state = "VERIFY_DOB"
                return "Aapki date of birth kya hai? For example, 1980-08-12."
            else:
                return "Mujhe lagta hai ki main galat person se baat kar raha hoon. Kya aap Mrs. Kavita Sharma hain?"
        elif self.state == "VERIFY_DOB":
            if user_input == self.patient_profile["date_of_birth"]:
                self.verified = True
                self.state = "CHECK_SYMPTOMS"
                return "Dhanyavaad. Ab main aapke health ke baare mein kuch sawal poochunga. Kya aapko fever hai?"
            else:
                return "Date of birth match nahi ho rahi hai. Kya aap sure hain?"
        elif self.state == "CHECK_SYMPTOMS":
            symptom = self.patient_profile["high_risk_symptoms_to_check"][self.symptom_index]
            if user_input.lower() in ["yes", "haan"]:
                self.high_risk_detected = True
            self.symptom_index += 1
            if self.symptom_index < len(self.patient_profile["high_risk_symptoms_to_check"]):
                next_symptom = self.patient_profile["high_risk_symptoms_to_check"][self.symptom_index]
                return f"Kya aapko {next_symptom.lower()} hai?"
            elif self.high_risk_detected:
                if self.raise_alert(symptom):
                    self.state = "CONCLUDE_ALERT"
                    return "Main aapki report on-call medical team ko bhej raha hoon. Koi chinta ki baat nahi hai, team aapko jaldi hi contact karegi."
                else:
                    self.state = "CONCLUDE_ALERT"
                    return "Alert raise karne mein problem hui. Main phir se try karunga."
            else:
                self.state = "CONCLUDE"
                return "Aapke koi high-risk symptoms nahi hain. Yeh achi baat hai. Aapko yaad dilana chahta hoon ki aapka follow-up consultation 5 din baad, yaani 20 May 2025 ko Dr. Jaideep Singh ke saath scheduled hai."
        elif self.state == "CONCLUDE_ALERT":
            self.state = "END"
            return "Ab main call khatam kar raha hoon. Dhanyavaad aur apna khayal rakhiye."
        elif self.state == "CONCLUDE":
            self.state = "END"
            return "Dhanyavaad aur apna khayal rakhiye. Goodbye."
        return "Mujhe samajh nahi aaya, please repeat."

    def raise_alert(self, symptom):
        payload = {
            "patient_id": self.patient_profile["patient_id"],
            "reported_symptoms": [symptom],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            "alert_level": "high"
        }
        try:
            response = requests.post(ALERT_API_URL, json=payload, timeout=1)
            return response.status_code == 200
        except:
            return False


class HealthcareAgent(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.transcript = []
        self.dm = DialogueManager(patient_profile)
        self.pipeline = None
        self.runner = None

    async def process_frame(self, frame, direction):
        if isinstance(frame, TextFrame):
            user_input = frame.text
            print(f"Patient: {user_input}")
            self.transcript.append(f"Patient: {user_input}")
            frame = await self.dm.process_frame(frame)
            print(f"Agent: {frame.text}")
            self.transcript.append(f"Agent: {frame.text}")
            return frame
        return frame

    def setup_pipeline(self):
        try:
            
            stt = DeepgramSTTService(
                api_key=os.getenv("DEEPGRAM_API_KEY"),
                language="en-IN"
            )
            nlu = CustomNLUProcessor()
            tts = ElevenLabsTTSService(
                api_key=os.getenv("ELEVENLABS_API_KEY"),
                voice_id="2bNrEsM0omyhLiEyOwqY"
            )
            params = LocalAudioTransportParams(
                sample_rate=16000,  
                channels=1,         
                frame_size=320      
            )            
            transport = LocalAudioTransport(params=params)

            
            self.pipeline = Pipeline([
                transport.input(),
                stt,
                nlu,
                self,
                tts,
                transport.output()
            ])
        except Exception as e:
            print(f"Error setting up pipeline: {e}")
            raise

    async def run(self):
        try:
            self.setup_pipeline()
            self.runner = CustomPipelineRunner()
            task = PipelineTask(self.pipeline)
            await self.runner.run(task)
        except Exception as e:
            print(f"Error running pipeline: {e}")
            raise

async def main():
    print("Starting Healthcare Voice Agent...")
    agent = HealthcareAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
