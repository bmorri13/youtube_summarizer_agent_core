"""Interactive local runner for YouTube Analyzer Agent."""

import sys

from dotenv import load_dotenv
load_dotenv()

from agent import run_agent


def main():
    """Interactive CLI loop."""
    print("=" * 60)
    print("YouTube Analyzer Agent")
    print("=" * 60)
    print("\nEnter a YouTube URL to analyze, or 'quit' to exit.\n")

    while True:
        try:
            url = input("YouTube URL: ").strip()

            if url.lower() in ("quit", "exit", "q"):
                print("\nGoodbye!")
                break

            if not url:
                print("Please enter a URL.\n")
                continue

            print(f"\nAnalyzing: {url}")
            print("-" * 50)

            result = run_agent(url)
            print(result)
            print("\n" + "=" * 60 + "\n")

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
