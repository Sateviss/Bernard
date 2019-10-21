import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.journal as journal
import bernard.database as database
import bernard.scheduler as scheduler
import asyncio
import aiohttp
import logging
import time

logger = logging.getLogger(__name__)
logger.info("loading...")

"""
TODO:
- Silence users in text, write to eventS_regulators
- publish events done via bot to #bernard
- public command to query reuglator actions
"""

@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def getid(ctx, target):
    if common.isDiscordRegulator(ctx.message.author):
        id = discord.get_targeted_id(ctx)
        await discord.bot.say(id)

#function to build the roles list allowed to be punished, this is kinda hacky
async def get_allowed_groups():
    global untouchable_roles
    untouchable_roles = []

    await discord.bot.wait_until_ready()
    await asyncio.sleep(1)

    #get all the roles, and make a list of them
    all_roles = discord.default_server.roles
    for role in all_roles:
        untouchable_roles.append(role.id)

    #remove default role
    untouchable_roles.remove(discord.default_server.default_role.id)

    #remove twitch role
    untouchable_roles.remove(config.cfg['discord']['twitch_managed_role'])

    # remove other roles in config.json that do not need to be protected
    for role in config.cfg['regulators']['unprotected_roles']:
        untouchable_roles.remove(role)

#this starts get_allowed_groups() at startup, but requires the bot to be ready
discord.bot.loop.create_task(get_allowed_groups())

#use the same check across all commands to see if the regulator is allowed to preform the action based on permission, role, status
def allow_regulation(message, target_id):
    #has to be a regulator+
    if common.isDiscordRegulator(message.author) == True:
        pass
    else:
        logger.debug("allow_regulation() attempted to invoke but was rejected for: no permission, Invoker: {}, Target:{}".format(message.author.id, target_id))
        return False

    #we need an ID to be able to work with, this should already be caught
    if target_id is None:
        return False

    #dont let the user try to play themselves
    if target_id == message.author.id:
        logger.debug("allow_regulation() attempted to invoke but was rejected for: attempted self harm, Invoker: {}, Target:{}".format(message.author.id, target_id))
        return False

    #if the user is an admin process it bypassing permissions
    if common.isDiscordAdministrator(message.author) == True:
        return True

    #convert the target_id into a member object, or at least try. This is to cacluate if the user can be touched
    target_member = discord.default_server.get_member(target_id)
    if target_member is None:
        logger.debug("allow_regulation() bypassing action restriction since Member object cannot be created. Invoker: {}, Target: {}".format(message.author.id, target_id))
        return True

    #get the assigned role IDs
    target_roles = []
    for role in target_member.roles:
        target_roles.append(role.id)

    #convert the lists to sets
    target_set = set(target_roles)
    untouchable_set = set(untouchable_roles)

    #if they intersect, they should not be touched
    allowed_set = untouchable_set.intersection(target_set)
    if len(allowed_set) == 0:
        return True
    else:
        logger.debug("allow_regulation() attempted to invoke but was rejected for: protected role, Invoker: {}, Target:{}".format(message.author.id, target_id))
        return False

    #failsafe to no if my bad logic fails
    logger.debug("allow_regulation() attempted to invoke but was rejected for: failsafe, Invoker: {}, Target:{}".format(message.author.id, target_id))
    return False

def allow_automod(msg):
    target_roles = []
    for role in msg.author.roles:
        target_roles.append(role.id)

    #convert the lists to sets
    target_set = set(target_roles)
    untouchable_set = set(untouchable_roles)

    allowed_set = untouchable_set.intersection(target_set)

    if len(allowed_set) == 0:
        return True
    else:
        return False

# formally warn a user, must supply a user mention and string longer than 4 chars to land
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def warn(ctx, target, *, reason):
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    # convert the target into a usable ID
    target_id = discord.get_targeted_id(ctx)
    target_member = await discord.get_user_info(target_id)
    if target_member is None:
        await discord.bot.say("{} ⚠️ I was not able to lookup that user ID.".format(ctx.message.author.mention))
        return

    # warn reason has to have at least a word in it
    if len(reason) < 4:
        await discord.bot.say("⚠️ Warning reason must be longer than 4 characters. `!warn @username reason goes here`")
        return

    # warn reason has to be a reasonable length
    if len(reason) > 200:
        await discord.bot.say("⚠️ Reason too long - please limit to 200 characters or less.")
        return

    if allow_regulation(ctx.message, target_id):
        # return what is happening in the same channel to alert the user
        await discord.bot.say("✔️ {} is warning {} with the reason of `{}`.".format(ctx.message.author.mention, target_member.mention, reason))

        # update the internal bot log
        journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="WARN_MEMBER", messageid=ctx.message.id)

        # update the internal user log
        journal.update_journal_event(module=__name__, event="ON_MEMBER_WARN", userid=target_id,
                                     contents="{0.name}#{0.discriminator} "
                                              "warned by {1.name}#{1.discriminator} "
                                              "with reason '{2}'".format(target_member, ctx.message.author, reason))
    else:
        await discord.bot.say("🛑 {} unable to moderate user. Either you failed to tag the user properly or the member is protected from regulators.".format(ctx.message.author.mention))


#kick a user from the server, must supply a user mention and string longer than 4 chars to land
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def kick(ctx, target, *, reason):
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    #convert the target into a usable ID
    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)
    if target_member is None:
        await discord.bot.say("{} ⚠️ I was not able to lookup that user ID.".format(ctx.message.author.mention))
        return

    #kick reason has to have at least a word in it
    if len(reason) < 4:
        await discord.bot.say("⚠️ Kick reason must be longer than 4 characters. `!kick @username reason goes here`")
        return

    # kick reason has to be a reasonable length
    if len(reason) > 200:
        await discord.bot.say("⚠️ Reason too long - please limit to 200 characters or less.")
        return

    if allow_regulation(ctx.message, target_id):
        #return what is happening in the same channel to alert the user, wait 5 seconds and fire the kick command
        try:
            await discord.bot.send_message(target_member, "You are being kicked with the reason of {}".format(reason))
        except discord.commands.errors.CommandInvokeError:
            pass
        await discord.bot.say("✔️ {} is kicking {} with the reason of `{}`.".format(ctx.message.author.mention, target_member.mention, reason))
        await asyncio.sleep(5)
        await discord.bot.kick(target_member)

        #update the internal bot log, since we cant send kick reasons via this api version #TODO: in rewrite add that
        journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="KICK_MEMBER", messageid=ctx.message.id)
    else:
        await discord.bot.say("🛑 {} unable to moderate user. Either you failed to tag the user properly or the member is protected from regulators.".format(ctx.message.author.mention))


#kick a user from the server, must supply a user mention and string longer than 4 chars to land
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def ban(ctx, target, *, reason):
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    #convert the target into a usable ID
    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)

    #ban reason has to have at least a word in it
    if len(reason) < 4:
        await discord.bot.say("⚠️ ban reason must be longer than 4 characters. `!ban @username reason goes here`")
        return

    # ban reason has to be a reasonable length
    if len(reason) > 200:
        await discord.bot.say("⚠️ Reason too long - please limit to 200 characters or less.")
        return

    #if the user cannot be banned
    if allow_regulation(ctx.message, target_id) is False:
        await discord.bot.say("🛑 {} unable to moderate user. (no permissions)".format(ctx.message.author.mention))
        return

    #if we have a Member object, it is not retroactive and can be run live against discord
    if target_member is not None:
        await discord.bot.say("✔️ {} is **BANNING** {} with the reason of `{}`.".format(ctx.message.author.mention, target_member.mention, reason))
        try:
            await discord.bot.send_message(target_member, "You are being **BANNED** with the reason of {}\n You can try begging for an unban here: {}".format(reason, config.cfg['bernard']['unban_form']))
        except discord.commands.errors.CommandInvokeError:
            pass
        await asyncio.sleep(5)
        res = await common.ban_verbose(target_member, "{} - '{}'".format(ctx.message.author.name, reason))
        if res is False:
            await discord.bot.say("❓ Something's fucked! Unable to issue ban to Discord API. Bother <@{}>".format(config.cfg['bernard']['owner']))
        else:
            journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="BAN_MEMBER", messageid=ctx.message.id)
        #if a raw mention exists but not the Member object, handle it as retroactive and log who did it.
    elif target_id is not None and target_member is None:
        await discord.bot.say("✔️ {} is (retroactive) **BANNING** userid `{}` with the reason of `{}`.".format(ctx.message.author.mention, target_id, reason))

        journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="BAN_MEMBER_RETROACTIVE", messageid=ctx.message.id)

        retroactive_reason = "VIA_RETROACTIVE: {} - '{}'".format(ctx.message.author.name, reason)
        database.cursor.execute('INSERT INTO bans_retroactive (id, name, reason) VALUES (%s,%s,%s)',(target_id, "N/A", retroactive_reason))
        database.connection.commit()
    else:
        await discord.bot.say("🛑 {} unable to moderate user. Target did not resolve to a valid Discord Member.".format(ctx.message.author.mention))

@discord.bot.command(pass_context=True, no_pm=True, hidden=True, aliases=['timeban'])
async def timedban(ctx, target, duration, *, reason):
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    #convert the target into a usable ID
    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)

    #ban reason has to have at least a word in it
    if len(reason) < 4:
        await discord.bot.say("⚠️ {0.message.author.mention} ban reason must be longer than 4 characters. `!ban @username 1d reason goes here`".format(ctx))
        return

    #if the user cannot be banned
    if allow_regulation(ctx.message, target_id) is False:
        await discord.bot.say("🛑 {0.message.author.mention} unable to moderate user. (no permissions)".format(ctx))
        return

    #verify the ban duration, and get the durations in seconds
    duration_length = scheduler.user_duration_to_seconds(duration)
    if duration_length is False:
        await discord.bot.say("⚠️{0.message.author.mention} unable to decode message length. Should be `!ban @username 60s|1m|7d could not stop using gamer words`".format(ctx))
        return
    elif duration_length is None:
        await discord.bot.say("⚠️{0.message.author.mention} unable to decode message length. allowed: seconds (s), minutes (m), hours (h), days (d), weeks (w), years (y)".format(ctx))
        return

    duration_inrange = scheduler.verify_reminder_duration_length(duration_length)
    if duration_inrange is False:
        await discord.bot.say("⚠️{0.message.author.mention} Ban duration is out of range. Have some mercy! Current range {1}m to {2}d".format(ctx, config.cfg['scheduler']['time_range_min_mins'], int(config.cfg['scheduler']['time_range_max_mins'] / 1440)))
        return

    #if we have a Member object, it is not retroactive and can be run live against discord
    if target_member is not None:
        #get the time to unban, make a db entry for unban
        now = int(time.time())
        time_to_fire = now + duration_length
        when_nice = time.strftime("%A, %B %d %Y %H:%M %Z", time.localtime(time_to_fire))

        scheduler.set_future_task(
            invoker=ctx.message.author.id,
            target=target_member.id,
            channel=ctx.message.channel.id,
            timestamp=time_to_fire,
            event="UNBAN_MEMBER",
            msg=reason)

        await discord.bot.say("✔️ {0.message.author.mention} is **BANNING** {1} with the reason of `{2}`. (Duration: {3}, Unban at:`{4}`)".format(ctx, target_member.mention, reason, duration, when_nice))
        try:
            await discord.bot.send_message(target_member, "You are being **BANNED** with the reason of {} (Duration: {}, Unban at:`{}`)\n You can try begging for an unban here: {}".format(reason, duration, when_nice, config.cfg['bernard']['unban_form']))
        except discord.commands.errors.CommandInvokeError:
            pass
        await asyncio.sleep(5)

        #ship the ban off to discord
        res = await common.ban_verbose(target_member, "{0.message.author.name} - '{1}'".format(ctx, reason))
        if res is False:
            await discord.bot.say("❓ Something's fucked! Unable to issue ban to Discord API. Bother <@{}>".format(config.cfg['bernard']['owner']))
        else:
            journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="BAN_MEMBER", messageid=ctx.message.id)
        #if a raw mention exists but not the Member object, handle it as retroactive
    elif target_id is not None and target_member is None:
        await discord.bot.say("⚠️ {0.message.author.mention} You cannot issue retroactive timed bans. Please use normal !ban.".format(ctx))
    else:
        await discord.bot.say("🛑 {0.message.author.mention} unable to moderate user. Target did not resolve to a valid Discord Member.".format(ctx))

#anti-raid/easy cleanup code, used to mass ban my ingress point
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def inviteban(ctx, target, *, reason):
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    # allow inviteban to be disabled
    if config.cfg['auditing']['inviteban']['enable'] == 0:
        await discord.bot.say("⚠️ {0.message.author.mention} !inviteban is disabled in config.json.".format(ctx))
        return

    # make sure the invite is not protected, useful for non-partner servers
    if target in config.cfg['auditing']['inviteban']['protected_invites']:
        await discord.bot.say("⚠️ {0.message.author.mention} Invite is protected in config.json and unable to be banned.".format(ctx))
        return

    # ban reason has to be a reasonable length
    if len(reason) < 4:
        await discord.bot.say("⚠️ {0.message.author.mention} Invite ban reason must be longer than 4 characters. `!inviteban inviteCode reason goes here`.".format(ctx))
        return

    # ban reason has to be a reasonable length
    if len(reason) > 200:
        await discord.bot.say("⚠️ {0.message.author.mention} Reason too long - please limit to 200 characters or less.".format(ctx))
        return

    #get anyone who joined via the invite
    database.cursor.execute("SELECT * FROM journal_events WHERE event='ON_MEMBER_JOINED_WITH_INVITE' AND contents=%s", (target,))
    invitees =  database.cursor.fetchall()

    #if there is not anyone, dont even do anything
    if len(invitees) == 0 or target.lower() == "none":
        await discord.bot.say("⚠️ {0.message.author.mention} Invalid invite code! 0 members joined via internal journal. Retype invite? (case sensitive)".format(ctx))
        return

    #get the invite data, make sure it is valid and then get who made it. They purge first.
    try:
        invite = await discord.bot.get_invite(target)
    except Exception as e:
        invite = None
        await discord.bot.say("⚠️ {0.message.author.mention} unable to look up invite code: {} for ownership! Moving on to blind mode!".format(ctx, e))

    #ban the inviter if we know who they are
    if invite is not None:
        banned_inviter = await common.ban_verbose(invite.inviter, "{} from invite {} - '{}'".format(ctx.message.author.name, target, reason))
        if banned_inviter == False:
            pass
            await discord.bot.say("❓ Something's fucked! Unable to issue ban to Discord API for root invite creator. Bother cake. (protected user?)")
        else:
            journal.update_journal_regulator(invoker=ctx.message.author.id, target=invite.inviter.id, eventdata=target, action="BAN_MEMBER_VIA_INVITE_MAKER", messageid=ctx.message.id)
            await discord.bot.say("✔️ {} is dropping the hammer on {} and anyone who joined via their invite `{}`. Let the bombs drop! ".format(ctx.message.author.mention, invite.inviter.mention, target))

    for invited in invitees:

        #attempt to turn the ID into a valid member object
        server = discord.bot.get_server(config.cfg['discord']['server'])
        invited_member = server.get_member(str(invited['userid']))

        #if that cant happen, the user probably left or was banned already. Add to retroactive table (TODO)
        if invited_member == None:
                database.cursor.execute('INSERT IGNORE INTO bans_retroactive(id, name, reason) VALUES(%s,%s,%s)', (invited['userid'], "UNKNOWN_INVITEBAN_CALLED", reason))
                database.connection.commit()
                await discord.bot.say("⚠️ `{}` is getting banned for joining on invite `{}` (retroactive fallback. User either left or already banned) ".format(invited['userid'], target))
        else:
            banned_inviter = await common.ban_verbose(invited_member, "{} inviteban via {} - '{}'".format(ctx.message.author.name, target, reason))
            if banned_inviter == False:
                await discord.bot.say("❓ Something's fucked! Unable to issue ban to Discord API for {}. Bother cake.".format(invited_member.mention))
            else:
                await discord.bot.say("✔️ {} is getting banned for joining on invite `{}` ".format(invited_member.mention, target))

        #take a break between to prevent r8 limited
        await asyncio.sleep(2)

    await discord.bot.say("Invite ban completed. {} members removed. Thanks for playing!".format(len(invitees)))

# handle unbans of regs own bans, also allow admins to unban anyone by id
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def unban(ctx, target):
    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)

    if common.isDiscordAdministrator(ctx.message.author):
        #if the user is an admin, let them blindly call IDs, unban blindly from discord
        unban_status_discord = await common.unban_id(target_id)

        #also check the retroactive table, this can be useful if the user was retro banned but never rejoied
        database.cursor.execute('SELECT * FROM bans_retroactive WHERE id=%s', (target_id,))
        unban_status_retroactive = database.cursor.fetchone()
        if unban_status_retroactive is None:
            unban_status_retroactive = False
        else:
            database.cursor.execute('DELETE FROM bans_retroactive WHERE id=%s', (target_id,))
            database.connection.commit()

        #unban message logic
        if unban_status_discord is False and unban_status_retroactive is False:
            await discord.bot.say("⚠️ Unable to find ID in either Discord or Retroactive table. Try again?")
        elif unban_status_discord is True and unban_status_retroactive is False:
            await discord.bot.say("✔️ User was found banned on Discord. Removed ban.")
        elif unban_status_discord is False and unban_status_retroactive is True:
            await discord.bot.say("✔️ User was found banned in Retroactive table. Removed from database.")
        else:
            await discord.bot.say("✔️ User was found banned on Discord and Retroactive ban table. Removed ban and database entry.")
    elif common.isDiscordRegulator(ctx.message.author):
        #regulators have a slightly different logic to follow to allow. Use internal audit log to make decisions
        database.cursor.execute('SELECT * FROM journal_regulators WHERE id_targeted=%s AND id_invoker=%s AND action="BAN_MEMBER" ORDER BY time ASC', (target_id, ctx.message.author.id))
        regulator_target_history = database.cursor.fetchone()

        #if there is nothing in the database there is no reason to even try with the logic
        if regulator_target_history is None:
            logger.warn("{0} attempted unban of {1} ID but failed due to reason: DB_RETURNED_NONE".format(ctx.message.author.id, target_id))
            await discord.bot.say("⚠️ {0.message.author.mention} Unable to find any record of you banning ID `{1}` (ever). You can only unban people you yourself banned.".format(ctx, target_id))
            return

        #get how many mins ago the ban was to see if they are able to be unbanned
        banned_mins_ago = int((time.time() - regulator_target_history['time']) / 60)

        #handle if we should process the unban_id()
        if banned_mins_ago > config.cfg['regulators']['unban_grace_mins']:
            over_grace_mins = int(banned_mins_ago - config.cfg['regulators']['unban_grace_mins'])
            logger.warn("{0} attempted unban of {1} ID but failed due to reason: OVER_GRACE_PERIOD by {2} minutes".format(ctx.message.author.id, target_id, over_grace_mins))
            await discord.bot.say("⚠️ {0.message.author.mention} The user ID `{1}` is over the grace period for regulator unbans by `{2}` minutes. Contact an Administrator.".format(ctx, target_id, over_grace_mins))
        else:
            unban_status_discord = await common.unban_id(target_id)
            if unban_status_discord is False:
                logger.warn("{0} attempted unban of {1} ID but failed due to reason: DISCORD_RETURNED_NOT_BANNED".format(ctx.message.author.id, target_id))
                await discord.bot.say("⚠️ {0.message.author.mention}  Discord returned no ban found for ID `{1}` (ever). The user was already unbanned or something is wrong :/".format(ctx, target_id))
            else:
                logger.info("{0} unbanned {1}. Time elapsed since ban {2}".format(ctx.message.author.id, target_id, banned_mins_ago))
                await discord.bot.say("✔️ {0.message.author.mention} ID `{1}` has been unbanned!".format(ctx, target))
                journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=banned_mins_ago, action="UNBAN_MEMBER_GRACE", messageid=ctx.message.id)

#strip member of rights to talk in voice rooms
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def silence(ctx, target, *, reason):
    if common.isDiscordVoiceRegulator(ctx.message.author) != True:
        return

    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)

    # silence reason has to have at least a word in it
    if len(reason) < 4:
        await discord.bot.say("⚠️ Silence reason must be longer than 4 characters. `!silence @username reason goes here`")
        return

    # silence reason has to have at least a word in it
    if len(reason) > 200:
        await discord.bot.say("⚠️ Reason too long - please limit to 200 characters or less.")
        return

    if allow_regulation(ctx.message, target_id) is False:
        await discord.bot.say("⚠️{} Permissions denied to regulate user".format(ctx.message.author.mention))
        return

    if target_member is not None:
        await discord.bot.server_voice_state(target_member, mute=1)
        journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=reason, action="VOICE_SILENCE", messageid=ctx.message.id)
        await discord.bot.say("✔️ {} was silenced by {} in voice chat".format(target_member.mention, ctx.message.author.mention))
    else:
        await discord.bot.say("🛑 {} unable to moderate user. Target did not resolve to a valid Discord Member.".format(ctx.message.author.mention))

#return member rights to talk in voice rooms
@discord.bot.command(pass_context=True, no_pm=True, hidden=True)
async def unsilence(ctx, target):
    if common.isDiscordVoiceRegulator(ctx.message.author) != True:
        return

    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id)

    if allow_regulation(ctx.message, target_id) is False:
        await discord.bot.say("⚠️{} Permissions denied to regulate user".format(ctx.message.author.mention))
        return

    if target_member is not None:
        await discord.bot.server_voice_state(target_member, mute=0)
        journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata="None", action="VOICE_UNSILENCE", messageid=ctx.message.id)
        await discord.bot.say("✔️ {} was unsilenced by {} in voice chat!".format(target_member.mention, ctx.message.author.mention))
    else:
        await discord.bot.say("🛑 {} unable to moderate user. Target did not resolve to a valid Discord Member.".format(ctx.message.author.mention))
