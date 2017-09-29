#!/usr/bin/env python3
from datetime import datetime, timedelta
import argparse
import logging
import random
import praw
import time
import sys

import strings
import argsfile

logger = logging.getLogger("giveawaybot")
logger.addHandler(logging.StreamHandler(sys.stdout))
logger.setLevel(logging.INFO)

def humanize_seconds(seconds):
  """
  Returns a humanized string representing time difference
  between now() and the input timestamp.

  The output rounds up to days, hours, minutes, or seconds.
  4 days 5 hours returns '4 days'
  0 days 4 hours 3 minutes returns '4 hours', etc...
  """
  minutes, seconds = divmod(seconds, 60)
  hours, minutes = divmod(minutes, 60)

  if hours > 0:
    if hours == 1:  return "{0} hour".format(hours)
    else:           return "{0} hours".format(hours)
  elif minutes > 0:
    if minutes == 1:return "{0} minute".format(minutes)
    else:           return "{0} minutes".format(minutes)
  elif seconds > 0:
    if seconds == 1:return "{0} second".format(seconds)
    else:           return "{0} seconds".format(seconds)
  else:
    return None

parser = argparse.ArgumentParser(description="Bot to run giveaways on Reddit.")

parser.add_argument('-a', '--age', type=int, default=1,
  help="The minimum age (in days) of user accounts that are eligible for "
    "the giveaway (prevents sockpuppet accounts)")

parser.add_argument('-p', '--poll', type=int, default=30,
  help="Seconds between polls for new comments. Recommended to be >30 seconds "
    "because Reddit caches results for that long.")

parser.add_argument('-k', '--keyword',
  help="If provided, this keyword must be present in the comment for it to "
    "be eligible for a prize. Prevents chatter from triggering a prize.")

parser.add_argument('--reply', choices=['inline', 'pm'], default='pm',
  help="Whether to reply with the prize inline or through pm. Defaults "
    "to pm.")

parser.add_argument('--random', default='store_true',
  help="Assigns prizes randomly instead of by submission time. -w is required "
        "if this argument is provided.")

parser.add_argument('-w', '--wait', type=int,
  help="Time in minutes to wait before checking comments. Only used in "
    "combination with --random. Recommended to be >30 minutes.")

group = parser.add_mutually_exclusive_group(required=True)

group.add_argument('-s', '--submission', default=None,
  help="URL of an existing post to crawl for submissions. Optional use "
    "instead of -r.")

group.add_argument('-r', '--reddit', default=None,
  help="The subreddit to post the giveaway to. This option creates a new "
    "post managed by the bot and must not be specified with -s.")

parser.add_argument('keyfile',
  help="A file path containing the keys to distribute (one per "
    "line). Leading and trailing whitespace will be removed from each key.")

args = parser.parse_args(sys.argv[1:])

if args.random and not args.wait:
  logger.error("Random assignment of prizes must specify a wait time (-w), "
    "otherwise first responders will have higher probability of winning. "
    "At least 30 minutes of wait time is recommended.")
  sys.exit(1)

argAge = args.age
argPoll = args.poll
argKeyword = args.keyword
argReply = args.reply
argRandom = args.random
argWait = args.wait
argSubmission = args.submission
argReddit = args.reddit
argKeyfile = args.keyfile

if argReddit == 'pcmasterrace':
  flair_open = argsfile.pcmr_flair_open
  flair_closed = argsfile.pcmr_flair_closed

elif argReddit == 'steam_giveaway':
  flair_open = argsfile.sg_flair_open
  flair_closed = argsfile.sg_flair_closed

else:
  flair_open = ''
  flair_closed = ''

min_account_age = timedelta(days=args.age)
accountAge = timedelta(days=104) #sets minimum account age

keys = []
try:
  with open(argKeyfile, 'r') as f:
    keys = f.readlines()
except IOError:
  logger.error("Could not open the key file {0}.".format(keyfile))
  sys.exit(1)

logger.info("Logging in...")
r = praw.Reddit('postaccount') #used for posting the giveaway
rmsg = praw.Reddit('msgaccount') #used to comment and send messages to users. Can be the same/different account

if argReddit:
  try:
    logger.info("Creating submission...")
    body = strings.submission_body

    if argKeyword:  # Alert users that they need a keyword
      body += "\n\n" + strings.keyword_message.format(keyword=argKeyword)

    if argRandom:  # Alert users that prizes are random
      utc_wait = (datetime.utcnow() + timedelta(minutes=argWait)).strftime("%H:%M:%S UTC")
      body += "\n\n" + strings.random_rule.format(wait=argWait, utc=utc_wait)
    else:  # Alert users that prizes
      body += "\n\n" + strings.timestamp_rule

    body += "\n\n" + strings.what_is_this
    rsub = r.subreddit(argReddit).submit(strings.submission_title.format(keys=len(keys)), selftext=body)
    argSubmission = rsub.shortlink
    logger.warning("Submission can be found at https://reddit.com" + str(rsub.permalink))
    if flair_open:
        rsub.flair.select(flair_open)
    rsub.disable_inbox_replies()
  except praw.exceptions.APIException as err:
    logger.error("Error with submission: " + str(err))

authors = set()
bannedUsers = set(line.strip() for line in open('banned.list'))
checked_comment_ids = set()

rsub = r.submission(url=argSubmission) #creates submission object
msgsub = rmsg.submission(url=argSubmission) #creates separate submission object for message user

if argRandom:
  logger.info("Sleeping for {0} minutes while users comment...".format(argWait))
  time.sleep(argWait * 60)

while len(keys) > 0:
  awarded = len(keys)
  logger.info("Checking comments...")

  msgsub.comments.replace_more(limit=None)
  comments = msgsub.comments.list()

  if argRandom:
    random.shuffle(comments)
  else:
    comments.sort(key=lambda c: c.created_utc)

  for comment in comments:
    if len(keys) == 0:
      break

    author = comment.author
    # Have we seen this comment before?
    if (author is not None and author.name not in authors and
        comment.id not in checked_comment_ids):
      checked_comment_ids.add(comment.id)
      # Ensure keyword is present if required
      if argKeyword and argKeyword not in comment.body:
        continue

      if (author.name in bannedUsers):
        logger.warn("Author {0} is on the banned users list".format(author.name))
        continue

      # Check account age
      created_date = datetime.fromtimestamp(int(author.created_utc))
      authors.add(author.name)
      if (datetime.now() - min_account_age) < created_date:
        logger.warn("Author {0} is too new.".format(author.name))
        continue

      if (datetime.now() - accountAge) < created_date:
        logger.warn("Author {0} is less then {1} days old.".format(author.name, accountAge))
        continue

      # We aren't using author karma, just a one month age. Why? Simple. I was a lurker for almost a year. 
      # I had no karma but I wasn't a spam account. I think a karma limit (even small) would limit more legit users then fake account.
      # but the code block is below just in case I want to implement it...

      #if ((author.link_karma < 50) or (author.comment_karma < 100)) and ((datetime.now() - accountAge) < created_date):
      #  logger.warn("Author {0} does not have enough Karma. Post Karma: {1}, Comment Karma: {2}".format(author.name, author.link_karma, author.comment_karma))
      #  continue


      try:
        message = strings.prize_reply_message.format(prize=keys.pop(0).strip(),
          url=argSubmission)
        if argReply == "inline":
          comment.reply(message)
        else:
          rmsg.redditor(author.name).message(strings.reply_title, message)
          comment.reply(strings.generic_reply_message)
      except AttributeError as err:
        logging.error("Missing value in strings file: {0}".format(err))
        sys.exit(1)

  if len(keys) < awarded:
    logger.info("Awarded {0} new prizes!".format(awarded - len(keys)))
  if len(keys) > 0:
    time.sleep(argPoll)

try:
  if rsub.selftext:
    rsub.edit(rsub.selftext + "\n\n**EDIT:** " + strings.end_message)
    if flair_closed:
      rsub.flair.select(flair_closed)
  else:
    rsub.edit(strings.end_message)
except praw.exceptions.APIException:
  logger.warning("Unable to edit original post to warn that giveaway "
    "is over. Recommend manually editing the post.")

logger.info("Prizes are all distributed, exiting.")
