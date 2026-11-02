"""AWS_IAMで保護したREST APIからfixtureのAG-UIストリームを検証する。"""

import argparse
import json
import logging
import re
import subprocess
import time
from uuid import uuid4

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="省略時はterraform outputから取得")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    url = (
        args.url
        or subprocess.check_output(
            [
                "terraform",
                "-chdir=terraform",
                "output",
                "-raw",
                "agent_invocations_url",
            ],
            text=True,
        ).strip()
    )
    if not re.fullmatch(
        r"https://[a-z0-9]+\.execute-api\.ap-northeast-1\.amazonaws\.com/poc/invocations",
        url,
    ):
        parser.error("東京リージョンのAPI Gateway /poc/invocations URLを指定してください。")

    run = {
        "threadId": str(uuid4()),
        "runId": str(uuid4()),
        "messages": [{"id": str(uuid4()), "role": "user", "content": "新宿区を年別に集計して"}],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
    }
    payload = json.dumps(run, ensure_ascii=False).encode()
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        parser.error("AWSの認証情報を設定してください。")
    request = AWSRequest(
        method="POST",
        url=url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", "ap-northeast-1").add_auth(
        request
    )
    observed = []
    with httpx.Client(timeout=httpx.Timeout(140, connect=10), follow_redirects=False) as client:
        # An unsigned request must fail before it can start an agent run.
        unsigned = client.post(url, content=payload, headers={"Content-Type": "application/json"})
        if unsigned.status_code != 403:
            raise RuntimeError("未署名リクエストが403で拒否されませんでした。")
        started = time.monotonic()
        with client.stream("POST", url, content=payload, headers=dict(request.headers)) as response:
            if response.status_code != 200:
                raise RuntimeError(f"中継のHTTPステータスが{response.status_code}でした。")
            if not response.headers.get("content-type", "").startswith("text/event-stream"):
                raise RuntimeError("中継の応答がSSEではありません。")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                elapsed = round(time.monotonic() - started, 3)
                observed.append((elapsed, event))
                print(
                    json.dumps(
                        {
                            "elapsed_s": elapsed,
                            "type": event["type"],
                            "name": event.get("name"),
                        }
                    ),
                    flush=True,
                )
                if len(observed) > 500:
                    raise RuntimeError("イベント数が検証上限を超えました。")
    events = [event for _, event in observed]
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_FINISHED"
    assert sum(e["type"] == "RUN_FINISHED" for e in events) == 1
    assert not any(e["type"] == "RUN_ERROR" for e in events)
    data = next(e["value"] for e in events if e.get("name") == "data_result")
    assert data["total_count"] == 3
    assert [r["year"] for r in data["preview_rows"]] == [2023, 2024, 2025]
    assert [r["transaction_count"] for r in data["preview_rows"]] == [40] * 3
    assert [r["average_price_yen"] for r in data["preview_rows"]] == [42_500_000] * 3
    statuses = [e["value"] for e in events if e.get("name") == "tool_status"]
    assert len(statuses) == 2 and all(s["status"] == "success" for s in statuses)
    metrics = next(e["value"] for e in events if e.get("name") == "run_metrics")
    assert metrics == {"model_calls": 3, "tool_calls": 2, "tool_errors": 0}
    assert all(
        "preview_rows" not in json.dumps(e) for e in events if e["type"] == "MESSAGES_SNAPSHOT"
    )
    text = [(t, e) for t, e in observed if e["type"] == "TEXT_MESSAGE_CONTENT"]
    assert "合成データ" in "".join(e["delta"] for _, e in text)
    assert text[-1][0] - text[0][0] >= 0.2, "テキストの逐次到着を確認できませんでした。"
    print(
        json.dumps(
            {
                "status": "passed",
                "events": len(events),
                "metrics": metrics,
                "first_event_s": observed[0][0],
                "first_text_s": text[0][0],
                "finished_s": observed[-1][0],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
