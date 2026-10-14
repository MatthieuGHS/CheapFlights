"""Liste les modèles Anthropic et les inference profiles Bedrock accessibles dans la région
de config.yaml. `--ping <id>` envoie un appel Converse d'un token pour prouver l'accès."""

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cheaphops.core.config import load_config


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--ping", metavar="MODEL_ID", help="model id ou inference profile id")
    args = ap.parse_args()

    llm = load_config(args.config).llm
    session = boto3.Session(profile_name=llm.profile, region_name=llm.region)
    print(f"profil={llm.profile} région={llm.region}\n")
    try:
        if args.ping:
            return ping(session, args.ping)
        list_models(session)
    except (ClientError, BotoCoreError) as e:
        print(f"erreur AWS : {e}", file=sys.stderr)
        return 1
    return 0


def list_models(session: boto3.Session) -> None:
    bedrock = session.client("bedrock")
    models = bedrock.list_foundation_models(byProvider="Anthropic")["modelSummaries"]
    print("Modèles de fondation Anthropic :")
    for m in sorted(models, key=lambda m: m["modelId"]):
        status = m.get("modelLifecycle", {}).get("status", "?")
        kinds = ",".join(m.get("inferenceTypesSupported", []))
        print(f"  {m['modelId']:<55} {status:<8} {kinds:<25} {m['modelName']}")

    print("\nInference profiles (à utiliser comme model_id si ON_DEMAND n'est pas listé) :")
    pages = bedrock.get_paginator("list_inference_profiles").paginate()
    profiles = [p for page in pages for p in page["inferenceProfileSummaries"]]
    for p in sorted(profiles, key=lambda p: p["inferenceProfileId"]):
        if "anthropic" in p["inferenceProfileId"]:
            print(f"  {p['inferenceProfileId']:<55} {p['status']:<8} {p['inferenceProfileName']}")
    print("\nVérifie l'accès avec --ping <id>, puis renseigne llm.fast/strong dans config.yaml")


def ping(session: boto3.Session, model_id: str) -> int:
    resp = session.client("bedrock-runtime").converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": "ping"}]}],
        inferenceConfig={"maxTokens": 1},
    )
    print(f"OK {model_id} : usage={resp['usage']} latence={resp['metrics']['latencyMs']} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
