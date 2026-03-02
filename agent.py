"""YouTube Analyzer Agent — LangGraph + ChatAnthropic."""

import os
import sys

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from observability import get_logger
from tools import ALL_TOOLS

# Load environment variables
load_dotenv()

# Configuration
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a YouTube video analyzer assistant. You can analyze individual videos or check channels for new content.

## When given a YouTube CHANNEL URL (contains /@, /channel/, /c/, or /user/):

1. **Get the latest video** using the get_latest_channel_video tool
   - This returns video info and indicates if it's already been processed (is_already_processed field)

2. **Check if already processed**:
   - If is_already_processed is true: Report that the video has already been analyzed and stop
   - If is_already_processed is false: Continue with analysis

3. **Fetch the transcript** using get_transcript with the video_url from step 1

4. **Analyze and save** (same as video workflow below, but use channel_id and channel_name from the get_latest_channel_video result)

## When given a YouTube VIDEO URL (contains /watch?v= or youtu.be/):

1. **Fetch the transcript** using the get_transcript tool
   - This returns the transcript along with video metadata (title, channel_name, video_url, video_id)
   - Store these metadata values to use in subsequent steps

2. **Analyze the content** and create a comprehensive summary with:
   - **Overview**: A 2-3 sentence summary of what the video is about
   - **Key Points**: 3-5 main takeaways as bullet points
   - **Notable Quotes**: 2-3 interesting or important direct quotes from the transcript
   - **Action Items/Takeaways**: Any actionable advice or recommendations mentioned

3. **Save the summary** as a note using the save_note tool
   - Include video_id from the transcript result to track the video as processed
   - If available (from channel workflow), also include channel_id and channel_name

4. **Send a Slack notification** using send_slack_notification with these REQUIRED parameters:
   - video_title: The title from the transcript metadata
   - channel_name: The YouTube channel name from the transcript metadata
   - video_url: The URL from the transcript metadata
   - overview: A brief 1-2 sentence summary
   - key_points: An array of 3-5 key takeaways (strings)
   - main_takeaway: (optional) The single most important insight

Format your analysis in clear markdown. Be concise but thorough.

If the transcript cannot be fetched (disabled, unavailable, etc.), inform the user and do not proceed with the other steps.
"""

def _create_model():
    """Create ChatAnthropic model."""
    return ChatAnthropic(model=CLAUDE_MODEL, max_tokens=4096)


def _build_config(max_turns=10):
    """Build LangGraph config."""
    return {"recursion_limit": (max_turns * 2) + 1}


def run_agent(video_url: str, max_turns: int = 10) -> str:
    """Run the YouTube analyzer agent."""
    logger = get_logger()

    model = _create_model()
    graph = create_react_agent(model, tools=ALL_TOOLS)

    config = _build_config(max_turns=max_turns)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Please analyze this YouTube video: {video_url}"),
    ]

    try:
        result = graph.invoke({"messages": messages}, config=config)
        final_message = result["messages"][-1]
        return final_message.content
    except Exception as e:
        logger.error(f"Agent error: {e}")
        raise


def run_agent_with_transcript(
    video_url: str,
    video_id: str,
    video_title: str,
    channel_name: str,
    transcript: str,
    channel_id: str = None,
    max_turns: int = 10,
) -> str:
    """Run agent with pre-fetched transcript (hybrid fetcher mode)."""
    logger = get_logger()

    # Filter out transcript/channel tools — agent already has the data
    filtered_tools = [t for t in ALL_TOOLS
                      if t.name not in ("get_transcript", "get_latest_channel_video")]

    model = _create_model()
    graph = create_react_agent(model, tools=filtered_tools)

    config = _build_config(max_turns=max_turns)

    # Build prompt with transcript embedded
    prefetch_prompt = f"""I already have the transcript for this video:
- Video URL: {video_url}
- Video ID: {video_id}
- Title: {video_title}
- Channel: {channel_name}
{f'- Channel ID: {channel_id}' if channel_id else ''}

<transcript>
{transcript}
</transcript>

Please analyze this transcript and create a summary. Save the note (include video_id: {video_id}{f', channel_id: {channel_id}' if channel_id else ''}, channel_name: {channel_name}) and send a Slack notification."""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prefetch_prompt),
    ]

    try:
        result = graph.invoke({"messages": messages}, config=config)
        final_message = result["messages"][-1]
        return final_message.content
    except Exception as e:
        logger.error(f"Agent error (prefetched): {e}")
        raise


def main():
    """CLI entry point."""
    logger = get_logger()

    if len(sys.argv) > 1:
        video_url = sys.argv[1]
    else:
        video_url = input("Enter YouTube URL: ").strip()

    if not video_url:
        print("Error: No video URL provided")
        sys.exit(1)

    print(f"\nAnalyzing video: {video_url}\n")
    print("-" * 50)

    logger.info(f"Starting analysis for: {video_url}")
    result = run_agent(video_url)
    print(result)
    logger.info("Analysis complete")


if __name__ == "__main__":
    main()
