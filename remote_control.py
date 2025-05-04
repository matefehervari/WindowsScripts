import os
import sys
import signal
import base64
import threading
import logging
import traceback
from types import SimpleNamespace
from typing import Callable
import webbrowser
from io import BytesIO
from time import sleep
from dataclasses import asdict, dataclass
from flask import Flask, request, jsonify 
from flask_cors import CORS
from PIL import Image
from werkzeug.serving import make_server

from capturing import Capturing

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

class CustomLogHandler(logging.Handler):
    def __init__(self, log_callback):
        super().__init__()
        self.log = log_callback

    def emit(self, record):
        log_entry = self.format(record)
        self.log(log_entry)


class RemoteControlThread(threading.Thread):
    def __init__(self, host=HOST, port=PORT, log: Callable[..., None]=print):
        threading.Thread.__init__(self)
        self.daemon = True  # Thread will shut down with main program
        self.log = log

        self.log_handler = CustomLogHandler(self.log)
        self.log_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

        # Create Flask App
        self.app = Flask("Remote control")
        CORS(self.app)
        self.setup_routes()

        # Attach the handler to Flask's logger
        self.app.logger.addHandler(self.log_handler)

        # Lower Flask's built-in logging level
        self.app.logger.setLevel(logging.INFO)

        self.server = make_server(host, port, self.app)
        self.ctx = self.app.app_context()


    def setup_routes(self):
        @self.app.route("/", methods=["POST"])
        def handle_request():
            print("test")
            try:
                json = request.get_json()
                req = Request(**json)
                
                if req.payload.startswith("data:image/png;base64,"):
                    self.log("Detected base64 PNG. Copying to clipboard...")
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
                        self.log(f"Processed action: {req.action} to URL {req.payload}")
                        return jsonify({"status": "browser opened"}), 200

                return jsonify({"error": "unkown action"}), 400
            except Exception as e:
                self.log("Error: ", e)
                return jsonify({"error": str(e)}), 500


    def run(self):
        try:
            self.log("Flask server starting...")
            self.ctx.push()
            with Capturing() as output:
                self.server.log_startup()
            for line in output:
                self.log(line)
            self.server.serve_forever()
        except Exception as e:
            self.log("[Error] ", traceback.format_exception(type(e), e, e.__traceback__))

    def shutdown(self):
        self.log("Flask server stopping...")
        self.server.shutdown()



def main():
    print("Creating threads...")
    flask_thread = RemoteControlThread()
    flask_thread.start()

    def signal_handler(*_):
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
