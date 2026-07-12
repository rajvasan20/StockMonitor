"""X/Twitter Thread Poster — Posts 5-tweet threads via Twitter API v2.

Posts the first tweet, then replies to it in sequence to build a thread.

Setup:
    1. Create a developer account at developer.x.com
    2. Create a Project > App with Read+Write permissions
    3. Set environment variables:
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

Usage:
    python run.py tweet TECHM          # Generate + post thread
    python run.py tweet TECHM --dry-run  # Preview without posting
"""

import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import tweepy

from shared.utils import logger


def _get_client() -> tweepy.Client:
    """Create authenticated Twitter API v2 client."""
    api_key = os.environ.get("X_API_KEY")
    api_secret = os.environ.get("X_API_SECRET")
    access_token = os.environ.get("X_ACCESS_TOKEN")
    access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET")

    missing = []
    if not api_key:
        missing.append("X_API_KEY")
    if not api_secret:
        missing.append("X_API_SECRET")
    if not access_token:
        missing.append("X_ACCESS_TOKEN")
    if not access_token_secret:
        missing.append("X_ACCESS_TOKEN_SECRET")

    if missing:
        raise ValueError(
            f"Missing X/Twitter API credentials: {', '.join(missing)}. "
            "Set them as environment variables or in .env file."
        )

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


def post_thread(tweets: list[str], dry_run: bool = False) -> list[dict]:
    """Post a list of tweets as a thread (each replying to the previous).

    Args:
        tweets: List of tweet texts (first is the main tweet).
        dry_run: If True, print tweets without posting.

    Returns:
        List of dicts with tweet_id and text for each posted tweet.
    """
    if dry_run:
        results = []
        for i, tweet in enumerate(tweets, 1):
            label = "MAIN" if i == 1 else f"REPLY {i-1}"
            logger.info(f"[DRY RUN] Tweet {i} ({label}) — {len(tweet)} chars:")
            logger.info(tweet)
            logger.info("")
            results.append({"tweet_id": f"dry_run_{i}", "text": tweet})
        return results

    client = _get_client()
    results = []
    prev_tweet_id = None

    for i, tweet_text in enumerate(tweets):
        try:
            if prev_tweet_id is None:
                # First tweet — standalone
                response = client.create_tweet(text=tweet_text)
            else:
                # Reply to previous tweet
                response = client.create_tweet(
                    text=tweet_text,
                    in_reply_to_tweet_id=prev_tweet_id,
                )

            tweet_id = response.data["id"]
            prev_tweet_id = tweet_id
            results.append({"tweet_id": tweet_id, "text": tweet_text})

            label = "MAIN" if i == 0 else f"REPLY {i}"
            logger.info(f"Posted tweet {i+1} ({label}): {tweet_id}")

            # Small delay between tweets to avoid rate limits
            if i < len(tweets) - 1:
                time.sleep(2)

        except tweepy.TweepyException as e:
            logger.error(f"Failed to post tweet {i+1}: {e}")
            # Continue with remaining tweets using last successful ID
            results.append({"tweet_id": None, "text": tweet_text, "error": str(e)})

    return results


def post_ticker_thread(ticker: str, dry_run: bool = False) -> list[dict] | None:
    """Generate and post a thread for a ticker.

    Convenience function that combines thread_generator + poster.
    """
    from x_poster.thread_generator import generate_thread

    thread = generate_thread(ticker)
    if not thread:
        logger.error(f"No thesis found for ticker: {ticker}")
        return None

    logger.info(f"Generated {len(thread)}-tweet thread for {ticker}")
    return post_thread(thread, dry_run=dry_run)
