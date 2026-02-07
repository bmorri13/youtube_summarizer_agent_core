"""YouTube Analyzer Agent - Using Anthropic Python SDK with tool use."""

import json
import os
import sys
import uuid

from dotenv import load_dotenv
import anthropic

from tools import (
    ALL_TOOLS,
    get_transcript,
    save_note,
    send_slack_notification,
    get_latest_channel_video,
    mark_video_processed,
    update_channel_checked,
)
from observability import (
    AgentObservability,
    trace_span,
    trace_function,
    log_agent_event,
    log_tool_call,
    log_llm_call,
    get_logger,
    sanitize_log_value,
)

# Load environment variables
load_dotenv()

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


@trace_function("handle_tool_call")
def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    logger = get_logger()

    # Sanitize tool_name for logging to prevent log injection
    safe_tool_name = sanitize_log_value(tool_name)
    with trace_span(f"tool.{safe_tool_name}", {"tool_name": safe_tool_name}):
        logger.info(f"Executing tool: {safe_tool_name}")

        if tool_name == "get_transcript":
            result = get_transcript(tool_input["video_url"])
            log_agent_event(
                "transcript_fetch",
                video_url=tool_input["video_url"],
                video_id=result.get("video_id"),
                status="success" if result.get("success") else "error",
                error=result.get("error")
            )
        elif tool_name == "get_latest_channel_video":
            result = get_latest_channel_video(tool_input["channel_url"])
            log_agent_event(
                "channel_check",
                channel_url=tool_input["channel_url"],
                video_id=result.get("video_id"),
                is_already_processed=result.get("is_already_processed"),
                status="success" if result.get("success") else "error",
                error=result.get("error")
            )
            # Update channel tracking if successful
            if result.get("success"):
                update_channel_checked(
                    channel_id=result.get("channel_id"),
                    channel_name=result.get("channel_name"),
                    channel_url=tool_input["channel_url"],
                    last_video_id=result.get("video_id")
                )
        elif tool_name == "save_note":
            result = save_note(
                title=tool_input["title"],
                content=tool_input["content"],
                video_id=tool_input.get("video_id"),
                channel_id=tool_input.get("channel_id"),
                channel_name=tool_input.get("channel_name")
            )
            log_agent_event(
                "note_saved",
                status="success" if result.get("success") else "error",
                error=result.get("error"),
                metadata={
                    "path": result.get("path"),
                    "video_id": tool_input.get("video_id")
                }
            )
        elif tool_name == "send_slack_notification":
            result = send_slack_notification(
                video_title=tool_input.get("video_title", ""),
                channel_name=tool_input.get("channel_name", ""),
                video_url=tool_input.get("video_url", ""),
                overview=tool_input.get("overview", ""),
                key_points=tool_input.get("key_points", []),
                main_takeaway=tool_input.get("main_takeaway"),
                message=tool_input.get("message"),
                channel=tool_input.get("channel")
            )
            log_agent_event(
                "slack_sent",
                status="success" if result.get("success") else "error",
                error=result.get("error"),
                metadata={"method": result.get("method")}
            )
        else:
            result = {"success": False, "error": f"Unknown tool: {tool_name}"}
            log_agent_event("unknown_tool", status="error", error=f"Unknown tool: {tool_name}")

        # Log tool call for observability
        log_tool_call(tool_name, tool_input, result)

        return json.dumps(result)


def run_agent(video_url: str, max_turns: int = 10, session_id: str = None) -> str:
    """Run the YouTube analyzer agent on a video URL.

    Uses the Anthropic Messages API with tool use in an agentic loop.
    """
    logger = get_logger()
    session_id = session_id or str(uuid.uuid4())

    # Use observability context
    with AgentObservability(session_id=session_id) as obs:
        with obs.trace_agent_run(video_url):
            client = anthropic.Anthropic()
            model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

            messages = [
                {"role": "user", "content": f"Please analyze this YouTube video: {video_url}"}
            ]

            final_response = ""
            total_input_tokens = 0
            total_output_tokens = 0

            for turn in range(max_turns):
                with trace_span(f"llm_turn_{turn}", {"turn": turn, "model": model}):
                    logger.info(f"Agent turn {turn + 1}/{max_turns}")

                    response = client.messages.create(
                        model=model,
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        tools=ALL_TOOLS,
                        messages=messages
                    )

                    # Track token usage
                    input_tokens = getattr(response.usage, 'input_tokens', 0)
                    output_tokens = getattr(response.usage, 'output_tokens', 0)
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens

                    log_llm_call(model, input_tokens, output_tokens)

                    # Check if we're done (no more tool use)
                    if response.stop_reason == "end_turn":
                        for block in response.content:
                            if block.type == "text":
                                final_response += block.text
                        logger.info(f"Agent completed after {turn + 1} turns")
                        break

                    # Process the response
                    assistant_content = []
                    tool_results = []

                    for block in response.content:
                        if block.type == "text":
                            final_response += block.text
                            assistant_content.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            assistant_content.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input
                            })

                            # Execute the tool
                            result = handle_tool_call(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result
                            })

                    # Add assistant message and tool results to conversation
                    messages.append({"role": "assistant", "content": assistant_content})

                    if tool_results:
                        messages.append({"role": "user", "content": tool_results})
                    else:
                        break

            # Log final metrics
            log_agent_event(
                "agent_metrics",
                video_url=video_url,
                metadata={
                    "total_turns": turn + 1,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "session_id": session_id,
                }
            )

            return final_response


def run_agent_with_transcript(
    video_url: str,
    video_id: str,
    video_title: str,
    channel_name: str,
    transcript: str,
    channel_id: str = None,
    max_turns: int = 10,
    session_id: str = None
) -> str:
    """Run agent with a pre-fetched transcript (skip transcript fetching step).

    This is used when the local fetcher has already fetched the transcript
    to bypass YouTube IP blocking.

    Args:
        video_url: URL of the YouTube video
        video_id: YouTube video ID
        video_title: Title of the video
        channel_name: Name of the YouTube channel
        transcript: Pre-fetched transcript text
        channel_id: Optional YouTube channel ID
        max_turns: Maximum number of agent turns
        session_id: Optional session ID for tracing

    Returns:
        Agent's final response text
    """
    logger = get_logger()
    session_id = session_id or str(uuid.uuid4())

    # Filter out tools that shouldn't be used with pre-fetched transcripts:
    # - get_transcript: transcript is already provided
    # - get_latest_channel_video: would trigger update_channel_checked() which
    #   does a read-modify-write on processed_videos.json, risking data loss
    excluded_tools = {"get_transcript", "get_latest_channel_video"}
    tools_without_transcript = [
        tool for tool in ALL_TOOLS
        if tool["name"] not in excluded_tools
    ]

    # Create a modified system prompt that includes the transcript
    system_prompt_with_transcript = f"""{SYSTEM_PROMPT}

IMPORTANT: The transcript has already been fetched for you. Here is the video information:

Video URL: {video_url}
Video ID: {video_id}
Video Title: {video_title}
Channel: {channel_name}
{f'Channel ID: {channel_id}' if channel_id else ''}

TRANSCRIPT:
{transcript}

Since the transcript is already provided above, DO NOT use the get_transcript tool.
Proceed directly to:
1. Analyze and summarize the content
2. Save notes using save_note tool (include video_id: {video_id}{f', channel_id: {channel_id}' if channel_id else ''}, channel_name: {channel_name})
3. Send Slack notification using send_slack_notification tool
"""

    # Use observability context
    with AgentObservability(session_id=session_id) as obs:
        with obs.trace_agent_run(video_url):
            client = anthropic.Anthropic()
            model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

            messages = [
                {"role": "user", "content": f"Please analyze this YouTube video: {video_url}"}
            ]

            final_response = ""
            total_input_tokens = 0
            total_output_tokens = 0

            for turn in range(max_turns):
                with trace_span(f"llm_turn_{turn}", {"turn": turn, "model": model}):
                    logger.info(f"Agent turn {turn + 1}/{max_turns} (pre-fetched transcript)")

                    response = client.messages.create(
                        model=model,
                        max_tokens=4096,
                        system=system_prompt_with_transcript,
                        tools=tools_without_transcript,
                        messages=messages
                    )

                    # Track token usage
                    input_tokens = getattr(response.usage, 'input_tokens', 0)
                    output_tokens = getattr(response.usage, 'output_tokens', 0)
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens

                    log_llm_call(model, input_tokens, output_tokens)

                    # Check if we're done (no more tool use)
                    if response.stop_reason == "end_turn":
                        for block in response.content:
                            if block.type == "text":
                                final_response += block.text
                        logger.info(f"Agent completed after {turn + 1} turns")
                        break

                    # Process the response
                    assistant_content = []
                    tool_results = []

                    for block in response.content:
                        if block.type == "text":
                            final_response += block.text
                            assistant_content.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            assistant_content.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input
                            })

                            # Execute the tool
                            result = handle_tool_call(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result
                            })

                    # Add assistant message and tool results to conversation
                    messages.append({"role": "assistant", "content": assistant_content})

                    if tool_results:
                        messages.append({"role": "user", "content": tool_results})
                    else:
                        break

            # Log final metrics
            log_agent_event(
                "agent_metrics",
                video_url=video_url,
                metadata={
                    "total_turns": turn + 1,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "session_id": session_id,
                    "prefetched_transcript": True,
                }
            )

            return final_response


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
