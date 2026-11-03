import json
import subprocess
import time
import urllib.error
import urllib.request


def compose(*arguments):
    return subprocess.check_output(["docker", "compose", *arguments], text=True).strip()


def request(base, path):
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def master():
    return compose(
        "exec",
        "-T",
        "sentinel-1",
        "redis-cli",
        "-p",
        "26379",
        "--raw",
        "SENTINEL",
        "get-master-addr-by-name",
        "flight-cache",
    ).splitlines()[0]


def wait_for(check, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise AssertionError("Recovery deadline exceeded")


def main():
    config = json.loads(compose("config", "--format", "json"))
    environment = config["services"]["booking"]["environment"]
    base = f"http://{compose('port', 'booking', '8000')}"
    path = "/flights?origin=SVO&destination=LED"
    assert request(base, path)[0] == 200
    original_master = master()
    assert original_master in {"redis-master", "redis-replica"}
    try:
        compose("stop", original_master)
        assert request(base, path)[0] == 200
        wait_for(lambda: master() != original_master, 45)
        assert request(base, path)[0] == 200
        assert request(base, path)[0] == 200
        print(f"Redis failover passed: {original_master} -> {master()}", flush=True)
    finally:
        compose("start", original_master)
    try:
        compose("stop", "flight")
        for _ in range(int(environment["CIRCUIT_FAILURE_THRESHOLD"])):
            status, _ = request(base, path)
            assert status in {503, 504}
        start = time.monotonic()
        status, body = request(base, path)
        assert status == 503 and body["code"] == "CIRCUIT_OPEN", body
        assert time.monotonic() - start < 1
        print("Circuit breaker OPEN fails immediately with HTTP 503", flush=True)
    finally:
        compose("start", "flight")
    wait_for(
        lambda: request(base, path)[0] == 200, float(environment["CIRCUIT_RESET_TIMEOUT"]) + 30
    )
    assert request(base, "/health")[1]["flight_circuit"] == "CLOSED"
    print("Circuit breaker HALF_OPEN -> CLOSED recovery passed", flush=True)


if __name__ == "__main__":
    main()
