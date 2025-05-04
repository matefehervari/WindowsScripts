from io import StringIO
import sys

STDOUT = "stdout"
STDERR = "stderr"

class Capturing(list):
    def __init__(self, capture=STDOUT):
        super().__init__()
        self.capute = capture

    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = self._stdoutio = StringIO()
        sys.stderr = self._stderrio = StringIO()
        return self

    def __exit__(self, *_):
        self.extend(self._stdoutio.getvalue().splitlines())
        self.extend(self._stderrio.getvalue().splitlines())
        del self._stdoutio
        del self._stderrio
        sys.stdout = self._stdout
        sys.stderr = self._stderr
