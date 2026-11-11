from pathlib import Path
from .dq import inspect
from .pipeline import build
from .ml import train
import json


def main():
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/dq_report.json').write_text(json.dumps(inspect('data'), indent=2))
    build()
    print(json.dumps(train(), indent=2))


if __name__ == '__main__':
    main()
