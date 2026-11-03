import io
import tokenize
from pathlib import Path

import grpc_tools
from grpc_tools import protoc


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "generated"
    output.mkdir(exist_ok=True)
    (output / "__init__.py").touch()
    result = protoc.main(
        [
            "protoc",
            f"-I{root / 'proto'}",
            f"-I{Path(grpc_tools.__file__).parent / '_proto'}",
            f"--python_out={output}",
            f"--grpc_python_out={output}",
            str(root / "proto" / "flight.proto"),
        ]
    )
    if result:
        raise SystemExit(result)
    for path in output.glob("*_pb2*.py"):
        source = path.read_text().replace(
            "import flight_pb2 as flight__pb2", "from generated import flight_pb2 as flight__pb2"
        )
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        path.write_text(tokenize.untokenize(t for t in tokens if t.type != tokenize.COMMENT))


if __name__ == "__main__":
    main()
