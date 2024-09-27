import argparse
import os


def configure():
    parser = argparse.ArgumentParser(description="Bot runner")
    parser.add_argument(
        "-u",
        "--url",
        type=str,
        required=False,
        help="URL of the Daily room to join")
    parser.add_argument(
        "-t",
        "--token",
        type=str,
        required=False,
        help="token of Daily room to join",
    )

    args, unknown = parser.parse_known_args()

    url   = args.url   or os.getenv("ROOM_URL")
    token = args.token or os.getenv("ROOM_TOKEN")

    if not url:
        raise Exception("No room specified. use the -u/--url option from the command line, or set ROOM_URL in your environment to specify a Daily room URL.")

    if not token:
        raise Exception("No token specified. use the -t/--token option from the command line, or set ROOM_TOKEN in your environment to specify a Daily room token.")

    return (url, token)