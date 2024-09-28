from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    return jsonify({"villeChoisie": "Rimouski"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
