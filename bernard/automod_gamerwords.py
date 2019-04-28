import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.database as database
import bernard.journal as journal
import bernard.scheduler as scheduler
import datetime
import logging
import re
import time
import asyncio

logger = logging.getLogger(__name__)
logger.info("loading...")

# debug command to dump last events
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def gamerword_debug(ctx, target):
    if not common.isDiscordRegulator(ctx.message.author):
        return

    target_id = discord.get_targeted_id(ctx)

    # get the forgiveness value and get how far back we should look
    cutoff = int(time.time() - config.cfg['automod']['forgiveness_days'] * 86400)
    database.cursor.execute('SELECT score_final,score_regex,score_prev_infractions,multiply_age_member,multiply_age_account,action from automod_gamerwords WHERE id_targeted=%s AND time>%s', (target_id, cutoff))
    dbres = database.cursor.fetchall()
    if len(dbres) == 0:
        await discord.bot.say("{0.message.author.mention} no actions found in the last {1[automod][forgiveness_days]} days.".format(ctx, config.cfg))
    else:
        table_result = common.dbtable_to_strtable(dbres)
        if table_result:
            await discord.bot.say("Last {0[automod][forgiveness_days]} days of automoderation against ID:{1} ```{2}```".format(config.cfg, target_id, table_result))
        else:
            await discord.bot.say("{0.message.author.mention} unable to retrieve table, result too big or something broke.".format(ctx))

def regex_scoring_msg(msg):
    # https://www.reddit.com/r/modhelp/comments/4g8lpo/would_you_be_willing_to_share_your_slur_filter_if/
    regex_mapping = config.cfg['automod']['regex_banned_words']

    msg_score = 0 # set the base score to 0
    msg_found = [] # build empty list for gamer words found
    for regex, weight in regex_mapping.items(): # loop through every regex case
        for word in msg.split(): # split the string up into words for multiplyers (someone spamming same slur over and over)
            for match in re.findall("\\b"+regex+"\\b", word, re.IGNORECASE): # search that word against the regex
                msg_score += weight # add up the score
                msg_found.append(word) # add the list
                #print(msg, match, regex, weight)

    if msg_score is not 0:
        print("regex_scoring_message(): WEIGHT: {}, MSG: {}".format(msg_score, msg))

    # build a dict to return that contains the score (int), and lists of words found clean/dirty
    return {
        "score": msg_score,
        "words": msg_found
    }
    

def censor_word(word):
    wordlen = len(word)

    # get the first and last char
    wordfirst = word[0]
    wordlast = word[-1]

    return wordfirst + "*" * (wordlen-2) + wordlast

def member_age_scoring(age):
    # in minutes, format: age, multiplier
    multiplier_map = {
        60: 5, # 60m
        360: 4, # 6 hours
        1440: 3, # 1 day
        4320: 3.5, # 3 days
        10080: 2, # 1 week
        20160: 1.5, # 2 weeks
        40320: 1.15 # 1 month
    }

    for map_age, weight in multiplier_map.items():
        if age < map_age:
            logger.info("member_age_scoring(): MEMBER MULTIPLIER: {}".format(weight))
            return weight

    return 0

def account_age_scoring(age):
    # in minutes, format: age, multiplier
    multiplier_map = {
        60: 10, # 1 hour
        1440: 7.5, # 1 day
        10080: 5, # 1 week
        40320: 2.5, # 1 month
        120960: 1.5, # 3 months
    }

    for map_age, weight in multiplier_map.items():
        if age < map_age:
            print("account_age_scoring(): ACCOUNT MULTIPLIER: {}".format(weight))
            return weight

    return 0

def account_join_time(account_id):
    database.cursor.execute('SELECT * from journal_events WHERE userid=%s AND event = \'ON_MEMBER_JOIN\' ORDER BY `time` DESC LIMIT 1', (account_id,))
    dbres = database.cursor.fetchone()
    if dbres is None:
        return 0
    else:
        time_since_join = int((time.time() - dbres['time']) / 60)
        return member_age_scoring(time_since_join)


def previous_automod_scoring(account_id):
    cutoff = int(time.time() - config.cfg['automod']['forgiveness_days']*86400)
    database.cursor.execute('SELECT * from automod_gamerwords WHERE id_targeted=%s AND time>%s', (account_id, cutoff))
    dbres = database.cursor.fetchall()
    if len(dbres) == 0:
        return 0

    total_score = 0
    for action in dbres:
        # get how many days ago the infraction was
        days_ago_action = round((time.time() - action['time']) / 86400, 2)

        # get the mulitiplier based on the age, age_multiplier = 1 if just happened, age_multiplier = 0.01 if about to fall off
        age_multiplier = (config.cfg['automod']['forgiveness_days'] - days_ago_action) / config.cfg['automod']['forgiveness_days']

        # total up the total amount of points "awared" without the multiplier
        weighted_score = action['score_regex'] * age_multiplier
        total_score += weighted_score
        #print(days_ago_action, age_multiplier, weighted_score, action['score_regex']) # this is such a shitshow ill keep this for later

    return int(total_score)

def get_punishment_tier(score):
    threshold_map = config.cfg['automod']['threshold']

    # handle the higher tier punishments
    for punishment_map, score_map in threshold_map.items():
        if score > score_map:
            logger.info("get_punishment_tier(): PUNISHEMENT TIER: {}".format(punishment_map))
            return punishment_map

    # failsafe to a soft warning, also catches when the score is less than the soft warn
    return "WARN_SOFT"

async def slur_filter(message):
    # get the score of the message contents
    regex_result = regex_scoring_msg(message.content)

    # if the message scored 0, we can ignore
    if regex_result['score'] == 0:
        return

    # if we got this far, we need to lookup their account age
    account_min_old = int((datetime.datetime.utcnow().timestamp() - message.author.created_at.timestamp()) / 60)
    account_age_score = account_age_scoring(account_min_old)

    # and the amount of time in the discord
    account_member_score = account_join_time(message.author.id)

    # and how many times they have recently been AUTomodded
    account_previous_score = previous_automod_scoring(message.author.id)

    multiplier = account_age_score + account_member_score
    if multiplier is not 0:
        final_score = (regex_result['score'] * multiplier) + account_previous_score
    else:
        final_score = regex_result['score'] + account_previous_score

    if final_score == 0:
        return # fail safe if the score is 0

    # if we made it here, time to push some punishments
    await discord.bot.delete_message(message) # delete the message from Discord
    journal.update_journal_event(module=__name__, event="ON_MESSAGE_DELETE_AUTOMOD", userid=message.author.id, eventid=message.id, contents=message.content) # update the users journal

    # decide how hard to punish the user, and punish them
    punishment = get_punishment_tier(final_score)

    # Get a censored string of what the user said to get automodded
    clean_gamerwords = []
    for gamerword in regex_result['words']:
        clean_gamerwords.append(censor_word(gamerword))
    clean_modded_words = ','.join(clean_gamerwords)

    # alert the user to what they have done
    await discord.bot.send_message(message.channel, "{0.author.mention} is being automoderated with enforcement **{1}**: `({2})`".format(message, punishment, clean_modded_words))
    await asyncio.sleep(2) # sleep for 2 seconds until the ban is fired

    if punishment == "BAN_PERMA":
        punishment_journal_type = "BAN_MEMBER"
        ban = await common.ban_verbose(message.author, "AUTOMOD BAN_PERMA SCORE:{}".format(final_score))
        if ban is False:
            await discord.bot.send_message(message.channel, "❓ Something's fucked! Unable to issue ban to Discord API. Bother <@{}>".format(config.cfg['bernard']['owner']))

    elif punishment == "BAN_24H" or punishment == "BAN_1H":
        punishment_journal_type = "BAN_MEMBER"
        ban = await common.ban_verbose(message.author, "AUTOMOD {0} SCORE:{1}".format(punishment, final_score))
        if ban is False:
            await discord.bot.send_message(message.channel, "❓ Something's fucked! Unable to issue ban to Discord API. Bother <@{}>".format(config.cfg['bernard']['owner']))
        else:
            if punishment == "BAN_24H":
                time_to_fire = time.time() + 86400
            else:
                time_to_fire = time.time() + 3600

            # don't forget to set the unban event
            scheduler.set_future_task(
                invoker=discord.bot.user.id,
                target=message.author.id,
                channel=message.channel.id,
                timestamp=time_to_fire,
                event="UNBAN_MEMBER",
                msg="Automod SCORE:{0} WORDS:{1}".format(final_score, clean_modded_words))

    elif punishment == "KICK":
        punishment_journal_type = "KICK_MEMBER"
        await discord.bot.kick(message.author)

    elif punishment == "WARN_HARD":
        punishment_journal_type = "WARN_MEMBER"
        await discord.bot.send_message(message.channel, "{0.author.mention} Please review the rules! Your message is not allowed and has been removed. A rapsheet warning has been issued.".format(message, punishment, final_score))
    else:
        punishment_journal_type = None
        await discord.bot.send_message(message.channel, "{0.author.mention} Please review the rules! Your message is not allowed and has been removed. Next time I may not be as nice. (unoffical warning)".format(message, punishment, final_score))

    # update the regulator log
    if punishment_journal_type is not None:
        journal.update_journal_regulator(
            invoker=discord.bot.user.id,
            target=message.author.id,
            eventdata="Automod POLICY:{0} SCORE:{1} WORDS:{2}".format(punishment, final_score, clean_modded_words),
            action=punishment_journal_type,
            messageid=message.id)

    # log the action to the database
    database.cursor.execute('INSERT INTO automod_gamerwords'
                            '(score_final, score_regex, score_prev_infractions, multiply_age_member, multiply_age_account, action, time, id_targeted, message)'
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                            (final_score, regex_result['score'], account_previous_score, account_member_score, account_age_score, punishment, time.time(), message.author.id, message.content))
    database.connection.commit()
