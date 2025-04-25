import os
import sys
import signal
import base64
import threading
from types import SimpleNamespace
import webbrowser
from io import BytesIO
from time import sleep
from dataclasses import asdict, dataclass
from flask import Flask, request, jsonify 
from flask_cors import CORS
from PIL import Image
from werkzeug.serving import make_server

platform = os.name

if platform == "nt":
    import win32clipboard as clp
else:
    clp = SimpleNamespace()



HOST = "192.168.2.1"
PORT = 1234


@dataclass
class Request:
    action: str
    payload: str

    def __str__(self):
        return str(asdict(self))

#
# def handle_request(request: Request):
#     match request.action:
#         case "open-browser":
#             subprocess.Popen([BROWSER_EXE, request.payload])
#             print(f"Processed action: {request.action} to URL {request.payload}")
#         case _:
#             print(f"Request unhandled: {request}")
#
# def client_thread(conn, addr):
#     print(f"Address {addr} connected")
#     buffer = ""
#     try:
#         with conn:
#             while True:
#                 data = conn.recv(1024)
#                 if not data:
#                     break
#                 buffer += data.decode()
#                 while "\n" in buffer:
#                     line, buffer = buffer.split("\n", 1)
#                     line = line.strip()
#                     if not line:
#                         continue
#
#                     try:
#                         request = json.loads(line)
#                         request = Request(**request)
#                         handle_request(request)
#                     except json.JSONDecodeError as e:
#                         print(f"Invalid JSON from {addr}: {e}")
#                     except TypeError as e:
#                         print("Received unexpected request format")
#     except Exception as e:
#         print(f"Connection error with addr {addr}: {e.__class__}")
#
# def start_server():
#     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
#         sock.bind((HOST, PORT))
#         sock.listen()
#
#         print(f"Server listening on {HOST}:{PORT}")
#         while True:
#             conn, addr = sock.accept()
#             threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()

if platform == "nt":
    def copy_image_to_clipboard(image: Image.Image):
        output = BytesIO()
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]  # strip BMP header for clipboard
        output.close()

        clp.OpenClipboard()
        clp.EmptyClipboard()
        clp.SetClipboardData(clp.CF_DIB, data)
        clp.CloseClipboard()


app = Flask("Remote Control")
CORS(app)

@app.route("/", methods=["POST"])
def handle_request():
    try:
        json = request.get_json()
        req = Request(**json)
        
        if req.payload.startswith("data:image/png;base64,"):
            print("Detected base64 PNG. Copying to clipboard...")
            base64_data = req.payload.split(",", 1)[1]
            image_data = base64.b64decode(base64_data)
            image = Image.open(BytesIO(image_data))
            
            if platform == "nt":
                copy_image_to_clipboard(image)
                return jsonify({"status": "image copied to clipboard"}), 200
            elif platform == "posix":
                return jsonify({"status": "image copy not yet supported"}), 200

        match req.action:
            case "open-browser":
                webbrowser.open_new_tab(req.payload)
                print(f"Processed action: {req.action} to URL {req.payload}")
                return jsonify({"status": "browser opened"}), 200

        return jsonify({"error": "unkown action"}), 400
    except Exception as e:
        print("Error: ", e)
        return jsonify({"error": str(e)}), 500

class FlaskThread(threading.Thread):
    def __init__(self, host=HOST, port=PORT):
        threading.Thread.__init__(self)
        self.server = make_server(host, port, app)
        self.ctx = app.app_context()
        self.daemon = True  # Thread will shut down with main program

    def run(self):
        print("Flask server starting...")
        self.ctx.push()
        self.server.serve_forever()

    def shutdown(self):
        print("Flask server stopping...")
        self.server.shutdown()




def main():
    print("Creating threads...")
    flask_thread = FlaskThread()
    flask_thread.start()

    def signal_handler(sig, frame):
        print("Caught signal, shutting down...")
        flask_thread.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)


if __name__ == '__main__':
    main()
