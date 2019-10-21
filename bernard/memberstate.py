import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.analytics as analytics
import bernard.database as database
import bernard.invites as invites
import bernard.journal as journal
import logging
import asyncio
import datetime

logger = logging.getLogger(__name__)
logger.info("loading...")

ignore_depart = []

#new member to the server. user = discord.User
@discord.bot.event
async def on_member_join(user):
    msgProcessStart = analytics.getEventTime()
    if common.isDiscordMainServer(user.server) is not True:
        return

    #the user got here somehow, get the discord.Invite object we *think* they came from
    invite = await invites.on_member_join_attempt_invite_source(user)

    #if the user is retroactively banned, handle it and issue the ban
    database.cursor.execute('SELECT * FROM bans_retroactive WHERE id=%s', (user.id,))
    retdb = database.cursor.fetchone()

    print(user.id, retdb)

    if retdb is not None:
        ignore_depart.append(user.id)
        try:
            await discord.bot.send_message(user, "You are being retroactively banned with the reason of {}\n You can try begging for an unban here: {}".format(retdb['reason'], config.cfg['bernard']['unban_form']))
        except discord.commands.errors.CommandInvokeError:
            pass
        await common.ban_verbose(user, "RETROACTIVE_BAN_VIA_BOT_DB - '{}'".format(retdb['reason']))
        await discord.bot.send_message(discord.mod_channel(),"{0} **Retroactive Ban:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}` REASON: `{2}`)".format(common.bernardUTCTimeNow(), user, retdb['reason']))
        journal.update_journal_event(module=__name__, event="RETROACTIVE_BAN", userid=user.id, contents=retdb['reason'])
        return

    ##send the message to the admin defined channel
    await discord.bot.send_message(discord.mod_channel(),"{0} **New User:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`) **Account Age:** {2} **From:** `{3}`".format(common.bernardUTCTimeNow(), user, common.bernardAccountAgeToFriendly(user), invite))

    #handle kicking / banning of "new" accounts
    if config.cfg['auditing']['account_age_min']['enable']:
        logger.info("on_member_join() Account age minimum is enabled: Minimum account age required {} minutes.".format(config.cfg['auditing']['account_age_min']['min_age_required']))
        account_age_minutes = int((datetime.datetime.utcnow().timestamp() - user.created_at.timestamp()) / 60)

        #if the users account is too new lets apply logic to kick or ban
        if account_age_minutes <= config.cfg['auditing']['account_age_min']['min_age_required']:
            journal.update_journal_event(module=__name__, event="ON_MEMBER_JOIN_ACCOUNT_TOONEW", userid=user.id, contents="{0.name}#{0.discriminator} - {1} mins old".format(user, account_age_minutes))
            #await discord.bot.send_message(user, config.cfg['auditing']['account_age_min']['enforcement_dm'])
            await asyncio.sleep(3)
            if config.cfg['auditing']['account_age_min']['enforcement'] == "ban":
                logger.warn("on_member_join() BANNING ID {0.id} for being too new. Account age was {1} minutes, config is {2} minute age..".format(user, account_age_minutes, config.cfg['auditing']['account_age_min']['min_age_required']))
                try:
                    await discord.bot.send_message(user, "You are being automatically banned because your account is too new")
                except discord.commands.errors.CommandInvokeError:
                    pass
                await common.ban_verbose(user, "BOT_BAN_VIA_ACCOUNT_TOONEW - {} min old".format(account_age_minutes))
            else:
                logger.warn("on_member_join() KICKING ID {0.id} for being too new. Account age was {1} minutes, config is {2} minute age.".format(user, account_age_minutes, config.cfg['auditing']['account_age_min']['min_age_required']))
                try:
                    await discord.bot.send_message(user, "You are automatically being kicked because your account is too new")
                except discord.commands.errors.CommandInvokeError:
                    pass
                await discord.bot.kick(user)


    #capture the event in the internal log
    journal.update_journal_event(module=__name__, event="ON_MEMBER_JOIN", userid=user.id, contents="{0.name}#{0.discriminator}".format(user))

    analytics.onMemberProcessTime(msgProcessStart, analytics.getEventTime())

#member leaving the server. user = discord.User
@discord.bot.event
async def on_member_remove(user):
    global ignore_depart
    msgProcessStart = analytics.getEventTime()
    if common.isDiscordMainServer(user.server) is not True:
        return

    #if the user was banned or removed for another reason dont issue the depart statement
    if user.id in ignore_depart:
        ignore_depart.remove(user.id)
        return

    await discord.bot.send_message(discord.mod_channel(),"{0} **Departing User:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`)".format(common.bernardUTCTimeNow(), user))

    #remove any invites from this user
    await invites.on_member_leave_invite_cleanup(user)

    #capture the event in the internal log
    journal.update_journal_event(module=__name__, event="ON_MEMBER_REMOVE", userid=user.id, contents="{0.name}#{0.discriminator}".format(user))

    analytics.onMemberProcessTime(msgProcessStart, analytics.getEventTime())

#member getting banned from the server. member = discord.Member
@discord.bot.event
async def on_member_ban(member):
    msgProcessStart = analytics.getEventTime()
    if common.isDiscordMainServer(member.server) is not True:
        return

    ignore_depart.append(member.id)
    await discord.bot.send_message(discord.mod_channel(),"{0} **Banned User:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`)".format(common.bernardUTCTimeNow(), member))

    #remove any invites from this user
    await invites.on_member_leave_invite_cleanup(member)


    #capture the event in the internal log
    journal.update_journal_event(module=__name__, event="ON_MEMBER_BANNED", userid=member.id, contents="{0.name}#{0.discriminator}".format(member))

    analytics.onMemberProcessTime(msgProcessStart, analytics.getEventTime())

#unban events server = discord.Server, user = discord.User
@discord.bot.event
async def on_member_unban(server, user):
    msgProcessStart = analytics.getEventTime()
    if common.isDiscordMainServer(server) is not True:
        return

    await discord.bot.send_message(discord.mod_channel(),"{0} **Unbanned User:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`)".format(common.bernardUTCTimeNow(), user))

    #check if the user was retroactively rebanned, if they were remove from said list.
    database.cursor.execute('SELECT * FROM bans_retroactive WHERE id=%s', (user.id,))
    retdb = database.cursor.fetchone()
    if retdb is not None:
        database.cursor.execute('DELETE FROM bans_retroactive WHERE id=%s', (user.id,))
        database.connection.commit()
        await discord.bot.send_message(discord.mod_channel(),"{0} **Retroactive Unban:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`)".format(common.bernardUTCTimeNow(), user))
        journal.update_journal_event(module=__name__, event="RETROACTIVE_UNBAN", userid=user.id, contents=retdb['reason'])

    #capture the event in the internal log
    journal.update_journal_event(module=__name__, event="ON_MEMBER_UNBAN", userid=user.id, contents="{0.name}#{0.discriminator}".format(user))

    analytics.onMemberProcessTime(msgProcessStart, analytics.getEventTime())


#user object changes. before/after = discord.Member
@discord.bot.event
async def on_member_update(before, after):
    msgProcessStart = analytics.getEventTime()
    if common.isDiscordMainServer(before.server) is not True:
        return

    #handle nickname changes
    if before.nick != after.nick:
        if before.nick is None:
            await discord.bot.send_message(discord.mod_channel(),"{0} **Server Nickname Added:** {1.mention} was `{1.name}` is now `{2.nick}` (ID:`{1.id}`)".format(common.bernardUTCTimeNow(), before, after))
            journal.update_journal_event(module=__name__, event="ON_MEMBER_NICKNAME_ADD", userid=after.id, contents="{0.name} -> {1.nick}".format(before, after))
        elif after.nick is None:
            await discord.bot.send_message(discord.mod_channel(),"{0} **Server Nickname Removed:** {1.mention} was `{1.nick}` is now `{2.name}` (ID:`{1.id}`)".format(common.bernardUTCTimeNow(), before, after))
            journal.update_journal_event(module=__name__, event="ON_MEMBER_NICKNAME_REMOVE", userid=after.id, contents="{0.nick} -> {1.name}".format(before, after))
        else:
            await discord.bot.send_message(discord.mod_channel(),"{0} **Server Nickname Changed:** {1.mention} was `{1.nick}` is now `{2.nick}` (ID:`{1.id}`)".format(common.bernardUTCTimeNow(), before, after))
            journal.update_journal_event(module=__name__, event="ON_MEMBER_NICKNAME_CHANGE", userid=after.id, contents="{0.nick} -> {1.nick}".format(before, after))

    #handle username changes
    if before.name != after.name:
        await discord.bot.send_message(discord.mod_channel(),"{0} **Discord Username Changed:** {1.mention} was `{1.name}` is now `{2.name}` (ID:`{1.id}`)".format(common.bernardUTCTimeNow(), before, after))
        journal.update_journal_event(module=__name__, event="ON_USERNAME_CHANGE", userid=after.id, contents="{0.name} -> {1.name}".format(before, after))

    analytics.onMemberProcessTime(msgProcessStart, analytics.getEventTime())
