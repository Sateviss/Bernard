import bernard.config as config
import bernard.database as database
import asyncio
import discord
import logging
import subprocess
import platform
from discord.ext import commands
from discord import embeds

logger = logging.getLogger(__name__)
logger.info("loading...")

bot_jobs_ready = False

evtloop = asyncio.get_event_loop()

bot = commands.Bot(command_prefix='!', max_messages=config.cfg['bernard']['messagecache'], description='Bernard, for Discord. Made with love by ILiedAboutCake', loop=evtloop)

@bot.event
async def on_ready():
    global bot_jobs_ready
    global default_server
    logger.info('Logged in as {0.user.name} ID:{0.user.id}'.format(bot))

    #make an object available of this Server
    default_server = bot.get_server(config.cfg['discord']['server'])

    #start db connection checker
    bot.loop.create_task(database.check_db_connection())

    await asyncio.sleep(5)

    if config.cfg['bernard']['debug']:
        gitcommit = subprocess.check_output(['git','rev-parse','--short','HEAD']).decode(encoding='UTF-8').rstrip()
        await bot.change_presence(game=discord.Game(name="Debug: {}".format(gitcommit)))
    else:
        logger.info('Setting game status as in as "{0}"'.format(config.cfg['bernard']['gamestatus']))
        await bot.change_presence(game=discord.Game(name=config.cfg['bernard']['gamestatus']))

    bot.remove_command('help')

    await asyncio.sleep(30)
    logger.info('Setting internal bot_jobs_ready flag to True')
    bot_jobs_ready = True

if config.cfg['bernard']['debug'] is False:
    @bot.event
    async def on_command_error(error, ctx):
        logger.info("Uncaught command triggered: \"{0}\" {1}".format(error, ctx))

def objectFactory(snowflake):
    return discord.Object(snowflake)

def mod_channel():
    return discord.Object(config.cfg['bernard']['channel'])
