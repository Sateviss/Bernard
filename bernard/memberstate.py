import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.analytics as analytics
import bernard.database as database
import bernard.invites as invites
import bernard.journal as journal
import bernard.subscriber as subscriber
import logging

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
    database.dbCursor.execute('''SELECT * FROM bans_retroactive WHERE id=?''', (user.id,))
    retdb = database.dbCursor.fetchone()
    if retdb is not None:
        ignore_depart.append(user.id)
        await common.ban_verbose(user, "RETROACTIVE_BAN_VIA_BOT_DB - '{}'".format(retdb[2]))
        await discord.bot.send_message(discord.mod_channel(),"{0} **Retroactive Ban:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}` REASON: `{2}`)".format(common.bernardUTCTimeNow(), user, retdb[2]))
        journal.update_journal_event(module=__name__, event="RETROACTIVE_BAN", userid=user.id, contents=retdb[2])
        return

    ##send the message to the admin defined channel
    await discord.bot.send_message(discord.mod_channel(),"{0} **New User:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`) **Account Age:** {2} **From:** `{3}`".format(common.bernardUTCTimeNow(), user, common.bernardAccountAgeToFriendly(user), invite))

    #do a subscriber check and assign any roles on joining
    check_sub = subscriber.subscriber_update(user)
    await check_sub.update_subscriber()

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

    #remove any cached subscriber information
    subscriber.on_member_remove_purgedb(user)

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

    #remove any cached subscriber information
    subscriber.on_member_remove_purgedb(member)

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
    database.dbCursor.execute('SELECT * FROM bans_retroactive WHERE id=?', (user.id,))
    retdb = database.dbCursor.fetchone()
    if retdb is not None:
        database.dbCursor.execute('DELETE FROM bans_retroactive WHERE id=?', (user.id,))
        database.dbConn.commit()
        await discord.bot.send_message(discord.mod_channel(),"{0} **Retroactive Unban:** {1.mention} (Name:`{1.name}#{1.discriminator}` ID:`{1.id}`)".format(common.bernardUTCTimeNow(), user))
        journal.update_journal_event(module=__name__, event="RETROACTIVE_UNBAN", userid=user.id, contents=retdb[2])

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
