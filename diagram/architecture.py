#!/usr/bin/env python3
"""
Generate architecture diagram for YouTube Analyzer Agent.

Requires:
    - pip install diagrams
    - brew install graphviz (macOS) or apt-get install graphviz (Linux)

Usage:
    python architecture.py
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.storage import S3
from diagrams.aws.devtools import XRay
from diagrams.aws.management import Cloudwatch
from diagrams.aws.compute import ECR
from diagrams.onprem.container import Docker
from diagrams.onprem.client import User
from diagrams.saas.chat import Slack
import os

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Create diagram in the same directory as the script
with Diagram(
    "YouTube Analyzer Architecture",
    filename=os.path.join(SCRIPT_DIR, "youtube_analyzer_architecture"),
    show=False,
    direction="LR",
    graph_attr={
        "fontsize": "20",
        "bgcolor": "white",
        "pad": "1.0",
        "nodesep": "0.8",
        "ranksep": "1.2",
        "splines": "spline",
    },
    edge_attr={
        "fontsize": "10",
        "fontname": "Helvetica-Bold",
    },
):
    # Home Server (source)
    with Cluster("Home Server (On-Premises)"):
        with Cluster("Docker Container"):
            fetcher = Docker("local_fetcher.py\n(Supercronic)")

    # AWS Cloud (processing)
    with Cluster("AWS Cloud"):
        ecr = ECR("ECR")

        with Cluster("Compute"):
            lambda_fn = Lambda("youtube-analyzer\nLambda")

        with Cluster("Storage"):
            s3 = S3("S3 Bucket\n(notes)")

        with Cluster("Observability"):
            cloudwatch = Cloudwatch("CloudWatch\nLogs")
            xray = XRay("X-Ray\nTraces")

    # External Services (destinations)
    with Cluster("External Services"):
        youtube = User("YouTube API")
        anthropic = User("Anthropic\nClaude API")
        slack = Slack("Slack\nWebhook")

    # Data Flow - Local Fetcher Path
    fetcher >> Edge(label="1. Fetch Videos", color="blue") >> youtube
    fetcher >> Edge(label="2. Check Processed", color="gray", style="dashed") >> s3
    fetcher >> Edge(label="3. Invoke", color="green") >> lambda_fn

    # AWS Infrastructure
    ecr >> Edge(label="Deploy", color="purple", style="dashed") >> lambda_fn

    # Lambda processing
    lambda_fn >> Edge(label="4. Analyze", color="orange") >> anthropic
    lambda_fn >> Edge(label="5. Save", color="blue") >> s3
    lambda_fn >> Edge(label="6. Notify", color="green") >> slack

    # Observability (no labels to reduce clutter)
    lambda_fn >> Edge(color="gray", style="dashed") >> cloudwatch
    lambda_fn >> Edge(color="gray", style="dashed") >> xray


if __name__ == "__main__":
    print(f"Diagram generated: {os.path.join(SCRIPT_DIR, 'youtube_analyzer_architecture.png')}")
