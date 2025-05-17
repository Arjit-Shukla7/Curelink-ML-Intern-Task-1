from flask import Flask, request
app = Flask(__name__)

@app.route('/alert', methods=['POST'])
def alert():
    print("Alert received:", request.json)
    return {"status": "success"}, 200

if __name__ == "__main__":
    app.run(port=5000)