import bernard.config as config
import bernard.common as common
import bernard.discord as discord
import bernard.analytics as analytics
import bernard.deleted as deleted
import bernard.journal as journal
import asyncio
import logging

logger = logging.getLogger(__name__)
logger.info("loading...")

# A bunch of this code has been backported from https://github.com/ILiedAboutCake/delet-this

@discord.bot.command(pass_context=True, hidden=True)
async def cleanup(ctx, target=None, history=100):
    start = analytics.getEventTime()
    if common.isDiscordRegulator(ctx.message.author) != True:
        return

    #make user input something usable first, conform outlandish commands to be sane
    if target is None and history is None:
        await discord.bot.say("Syntax: `!cleanup @mention <1-1000>` where # is last x chat messages to check per channel. Defaults to 100.")
        return
    elif target is None:
        await discord.bot.say("Error: You must target a user by `@mention` or raw ID.")
        return
    elif history > 1000:
        await discord.bot.say("Warning: This command only supports up to the last 1000 channel messages. Limiting your request to 1000.")
        history = 1000
    else:
        pass

    #get the raw mention or just pass the ID depending on what the use supplied. member only needed for protection
    target_id = discord.get_targeted_id(ctx)
    target_member = discord.default_server.get_member(target_id) # Only use the Member lookup for Reg/Admin protection

    #if xiphirx = soy
    if target_id == discord.bot.user.id:
        await discord.bot.say("⚠️{0.message.author.mention} you are not allowed to cleanup after the bot!".format(ctx))
        return

    #dont allow this to be called on regulators/administrators
    if target_member is not None:
        if common.isDiscordRegulator(target_member):
            logger.warn("cleanup() called and is exiting: ID:{0.message.author.id} attempted to call cleanup on ID:{1} but was denied by: IS_REGULATOR_PROTECTED".format(ctx, target_id))
            await discord.bot.say("⚠️{0.message.author.mention} you are not allowed to call that on other admins/regulators!".format(ctx))
            return


    #while this runs lets not flood the mod channel with messages
    deleted.IGNORE_IDS.append(target_id)

    await discord.bot.say("{0.message.author.mention} starting now ID:`{1}` and will @ you when task completed.".format(ctx, target_id))
    logger.info("cleanup() {0.message.author.name} started deletion on ID:{1}. Checking all channels last {2} messages.".format(ctx, target_id, history))
    for channel in ctx.message.server.channels:
        if channel.type == discord.discord.ChannelType.text:
            logger.info("cleanup() {0.message.author.name} started deletion on channel ID: {0.message.channel.id} for user ID:{1}".format(ctx, target_id))
            await delete_messages_from_channel(ctx, channel, target_id, history)

    #no need to keep the id around
    deleted.IGNORE_IDS.remove(target_id)

    #create both a journal entry for the user targeted
    journal.update_journal_event(module=__name__, event="MESSAGE_CLEANUP_MODERATOR", userid=target_id, contents="Invoked by: {0.author.name} in channel {0.channel}".format(ctx.message))
    journal.update_journal_regulator(invoker=ctx.message.author.id, target=target_id, eventdata=history, action="MESSAGE_CLEANUP_MODERATOR", messageid=ctx.message.id)

    secs_taken = int(analytics.getEventTime() - start)
    await discord.bot.say("{0.message.author.mention} cleanup on ID `{1}` completed! Took ~{2} seconds".format(ctx, target_id, secs_taken))

async def delete_messages_from_channel(ctx, channel, target, history):
    async for message in discord.bot.logs_from(channel, limit=history):
        if message.author.id == target:
            logger.info("delete_messages_from_channel() deleting MSGID:{0.id} from CHANNELID:{1.id} from USERID:{0.author.id}".format(message, channel))
            await discord.bot.delete_message(message)

