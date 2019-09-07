import bernard.config as config
import datetime
import time
import json
import aiohttp
import logging
from tabulate import tabulate

logger = logging.getLogger(__name__)
logger.info("loading...")

#really dangerous commands, evals and raw bot exec etc
def isDiscordBotOwner(id):
    return id == config.cfg['bernard']['owner']

#commands that can lead to damage, but not the bot
def isDiscordAdministrator(member):
    if isDiscordBotOwner(member.id): return True

    try:
        for role in member.roles:
            if role.id == config.cfg['bernard']['administrators']: return True
    except AttributeError:
        return False

    return False

#regulators that can control some basic mod tasks
def isDiscordRegulator(member):
    if isDiscordBotOwner(member.id): return True
    if isDiscordAdministrator(member): return True

    try:
        for role in member.roles:
            if role.id in config.cfg['bernard']['regulators']:
                return True
    except AttributeError:
        return False

    return False

#common name for this role is a deputy, this grants the least power
def isDiscordVoiceRegulator(member):
    if isDiscordBotOwner(member.id):
        return True
    elif isDiscordAdministrator(member):
        return True
    elif isDiscordRegulator(member):
        return True
    else:
        try:
            for role in member.roles:
                if role.id in config.cfg['bernard']['voice_regulators']:
                    return True
                else:
                    return False
        except AttributeError:
            return False

    return False


def datetimeObjectToString(timestamp):
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")

def isDiscordMainServer(server):
    if server is None:
        return False

    if server.id == config.cfg['discord']['server']:
        return True

def bernardUTCTimeNow():
    return datetime.datetime.utcnow().strftime(config.cfg["bernard"]["timestamp"])

def bernardUTCEpochTimeNow():
    return datetime.datetime.utcnow().timestamp()

def bernardTimeToEpoch(age):
    return datetime.datetime(age).timestamp()

def bernardAccountAgeToFriendly(user):
    diff = int(datetime.datetime.utcnow().timestamp() - user.created_at.timestamp())

    years, rem = divmod(diff, 31104000)
    months, rem = divmod(rem, 2592000)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)

    return "{:02d}:{:02d}:{:02d}:{:02d}:{:02d}:{:02d}".format(years, months, days, hours, mins, secs)

#this should always return a discord.User
def target_user(ctx, target=None):
    #if we only got the context we only have the context
    if target is None:
        return ctx.message.author

    #check if the user is allowed to modify the target
    if isDiscordAdministrator(ctx.message.author) is not True:
        return ctx.message.author

    #if there is a mention use that for the user objext returned
    if len(ctx.message.mentions) == 1:
        return ctx.message.mentions[0]

    #if we got this far we are working with a string of either an ID or a named member
    named = ctx.message.server.get_member_named(target)
    snowflake = ctx.message.server.get_member(target)

    #one of these should be true, if neither are return None
    if named:
        return named
    elif snowflake:
        return snowflake
    else:
        return None

# input a List from the database query, get a string formatted table with headers safe for Discord
def dbtable_to_strtable(dbres):
    columns = []
    columns.append(list(dbres[0].keys())) #this gets the header for tabulate

    for res in dbres:
        columns.append(list(res.values())) #this builds the rows of the results

    #tabulate this into a string https://pypi.python.org/pypi/tabulate
    postdb = tabulate(columns, headers="firstrow")

    #check the length
    if len(postdb) >= 1990:
        return False
    else:
        return postdb

async def getJSON(url, tmout=5, hdrs=None):
    url_safe = url_safe.replace(config.cfg['discord']['token'], "<HIDDEN>")
    logger.info("common.getJSON() attempting async URL {0} Timeout:{1}s".format(url_safe, tmout))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=tmout, headers=hdrs) as r:
                logger.info("common.getJSON() returned HTTP/{}".format(r.status))
                if r.status == 200:
                    if "application/json" in r.headers['Content-Type']:
                        ret = await r.json()
                        return ret
                    else:
                        logger.warn("common.getJSON() unable to get JSON from endpoint. Content-Type mismatched {}".format(r.headers['Content-Type']))
                        return None
                else:
                    logger.warn("common.getJSON() unable to get JSON from endpoint. HTTP code not valid HTTP/{}".format(r.status))
                    return None
    except Exception as e:
        logger.error("common.getJSON() threw an exception: {0}".format(e))
        return None

#this is easier than porting to rewrite
async def ban_verbose(user, reason):
    try:
        url = config.cfg['discord']['endpoint'] + "/guilds/" + config.cfg['discord']['server'] + "/bans/" + user.id
        params = [('reason', reason), ('delete-message-days', 0)]
        async with aiohttp.put(url, params=params, headers={'Authorization':'Bot '+ config.cfg['discord']['token']}) as r:
            logger.info("common.ban_verbose() attempting async URL {0} params {1}".format(url, params))
            if r.status == 204:
                return True
            else:
                logger.warn("common.ban_verbose() unable to PUT to endpoint. HTTP code not valid HTTP/{}".format(r.status))
                return False

    except Exception as e:
        logger.error("common.ban_verbose() threw an exception: {0}".format(e))
        return False

#handle unbans by id instead of having to make an object just to delete it :/
async def unban_id(userid):
    try:
        url = config.cfg['discord']['endpoint'] + "/guilds/" + config.cfg['discord']['server'] + "/bans/" + userid
        async with aiohttp.delete(url, headers={'Authorization':'Bot '+ config.cfg['discord']['token']}) as r:
            logger.info("common.unban_id() attemping to async URL {0}".format(url))
            if r.status == 204:
                return True
            else:
                logger.warn("common.unban_id() returning false, got status code {} from discord.".format(r.status))
                return False
    except Exception as e:
        logger.error("common.unban_id() threw and exception {}".format(e))
        return False
