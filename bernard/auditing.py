import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.database as database
import bernard.journal as journal
import logging
import tldextract
import re

logger = logging.getLogger(__name__)
logger.info("loading...")

async def attachments(msg):
    if config.cfg['auditing']['attachments']['enable'] == 0:
        return

    if common.isDiscordAdministrator(msg.author):
        return

    if msg.attachments is False:
        return

    for attachment in msg.attachments:
        exploded = attachment['filename'].split(".")[1:]
        for ext in exploded:
            ext = ext.replace(".","").replace("-","")
            if ext in config.cfg['auditing']['attachments']['restricted']:
                await discord.bot.delete_message(msg)
                await discord.bot.send_message(msg.channel, "{0}, <:pepoG:352533294862172160> that file format is not allowed to be uploaded here. Filename: `{1}`".format(msg.author.mention, attachment['filename']))
                journal.update_journal_event(module=__name__, event="AUDIT_DELETE_ATTACHMENT", userid=msg.author.id, eventid=msg.id, contents=attachment['filename'])
                logger.warn("deleting uploaded file: {0}".format(attachment['filename']))

async def discord_invites(msg):
    #enable the module or not
    if config.cfg['auditing']['invites']['enable'] == 0:
        return

    #ignore admins we dont even care what they do
    if common.isDiscordAdministrator(msg.author):
        return

    #use regex to find discord.gg links in all shapes and sizes, stop if we dont find any
    matched_discord = re.findall('discord.*gg\/([^\s]+)', msg.content.lower())
    if len(matched_discord) == 0:
        return

    #if the config is using the @everyone role
    if config.cfg['auditing']['invites']['lowest_role_blocked'] == "everyone":
        if msg.author.top_role.is_everyone == True:
            await discord.bot.delete_message(msg)
            await discord.bot.send_message(msg.channel, "⚠️ {0} Members without a role are unable to post Discord invites.".format(msg.author.mention))
            logger.warn("deleted invite {0} under reason: 'everyone role'".format(matched_discord[0]))
            journal.update_journal_event(module=__name__, event="AUDIT_DELETE_INVITE", userid=msg.author.id, eventid=msg.id, contents=matched_discord[0])
    elif msg.author.top_role.id == config.cfg['auditing']['invites']['lowest_role_blocked']:
            await discord.bot.delete_message(msg)
            await discord.bot.send_message(msg.channel, "⚠️ {0} Your role does not meet the minimum requirements to post Discord invites.".format(msg.author.mention))
            logger.warn("deleted invite {0} under reason: 'underpowered role'".format(matched_discord[0]))
            journal.update_journal_event(module=__name__, event="AUDIT_DELETE_INVITE", userid=msg.author.id, eventid=msg.id, contents=matched_discord[0])
    else:
        logger.warn("allowing discord user to post invite link: {0}".format(matched_discord[0]))

#CREATE TABLE `auditing_blacklisted_domains` ( `domain` TEXT UNIQUE, `action` TEXT, `added_by` TEXT, `added_when` INTEGER, `hits` INTEGER DEFAULT 0 )
async def blacklisted_domains(msg):
    if config.cfg['auditing']['blacklisted_domains']['enable'] == 0:
        return

    if common.isDiscordAdministrator(msg.author):
        return

    #matched regex into URLs list
    full_urls = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', msg.content)
    if len(full_urls) == 0:
        return

    for url in full_urls:
        #extract the url into only what we care about https://github.com/john-kurkowski/tldextract
        tldext = tldextract.extract(url)
        domain = "{0.domain}.{0.suffix}".format(tldext)

        #lookup the tld in the db
        database.cursor.execute('SELECT * FROM auditing_blacklisted_domains WHERE domain=%s', (domain.lower(),))
        dbres = database.cursor.fetchone()

        #if we dont find the domain just move along
        if dbres == None:
            continue

        #up the hit counter in the DB
        database.cursor.execute('UPDATE auditing_blacklisted_domains SET hits=%s WHERE domain=%s', (dbres['hits']+1,domain))
        database.connection.commit()

        #if we found a domain lets act on it | methods audit / delete / kick / ban
        if dbres['action'] == "audit":
            logger.info("Domain audit of user {0.author} blacklisted_domains() domain {1[domain]} found".format(msg, dbres))
        elif dbres['action'] == "delete":
            logger.warn("blacklisted_domains() message delete from domain {0[domain]} for user {1.author} ({1.author.id})".format(dbres, msg))
            await discord.bot.delete_message(msg)
            await discord.bot.send_message(msg.channel, "⚠️ {0.author.mention} that domain `{1[domain]}` is prohibited here.".format(msg, dbres))
            journal.update_journal_event(module=__name__, event="AUDIT_DOMAIN_DELETE", userid=msg.author.id, eventid=msg.id, contents=dbres['domain'])
            return
        elif dbres['action'] == "kick":
            logger.warn("blacklisted_domains() user kick from domain {0[domain]} for user {1.author} ({1.author.id})".format(dbres, msg))
            await discord.bot.delete_message(msg)
            try:
                await discord.bot.send_message(msg.author, "That domain `{}` is prohibited with the policy to kick poster.".format(dbres["domain"]))
            except discord.commands.errors.CommandInvokeError:
                pass
            await discord.bot.send_message(msg.channel, "🛑 {0.author.mention} that domain `{1[domain]}` is prohibited here with the policy to kick poster. Kicking...".format(msg, dbres))
            await discord.bot.kick(msg.author)
            journal.update_journal_event(module=__name__, event="AUDIT_DOMAIN_KICK", userid=msg.author.id, eventid=msg.id, contents=dbres['domain'])
            return
        elif dbres['action'] == "ban":
            logger.warn("blacklisted_domains() user ban from domain {0[domain]} for user {1.author} ({1.author.id})".format(dbres, msg))
            await discord.bot.delete_message(msg)
            try:
                await discord.bot.send_message(msg.author, "That domain `{}` is prohibited with the policy to **BAN** poster.\n You can try begging for an unban here: {}".format(dbres["domain"], config.cfg['bernard']['unban_form']))
            except discord.commands.errors.CommandInvokeError:
                pass
            await discord.bot.send_message(msg.channel, "🛑 {0.author.mention} that domain `{1[domain]}` is prohibited here with the policy to **BAN** poster. Banning...".format(msg, dbres))
            await common.ban_verbose(msg.author, "BOT_AUTOBAN_FOR_BLACKLISTED_DOMAIN - 'Domain:{0[domain]} URL:{1}'".format(dbres, url))
            journal.update_journal_event(module=__name__, event="AUDIT_DOMAIN_BAN", userid=msg.author.id, eventid=msg.id, contents=dbres['domain'])
            return
        else:
            logger.error("Unknown action attempted in blacklisted_domains() while handling a blacklisted domain {0[domain]} method {0[action]}".format(dbres))
