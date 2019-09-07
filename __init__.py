import logging
import bernard.config

logging.basicConfig(level=logging.INFO, format=bernard.config.cfg['bernard']['logging']['format'], datefmt=bernard.config.cfg['bernard']['logging']['dateformat'])
logger = logging.getLogger(__name__)
logger.info("Attempting to start. I can't promise you I will work but I can sure try.")

#always import common, discord in that order or things will break
import bernard.common
import bernard.discord
import bernard.database
import bernard.analytics
import bernard.journal

#chat modules
import bernard.hello
import bernard.administrate

#moderation modules
import bernard.message
import bernard.auditing
import bernard.purger
import bernard.memberstate
import bernard.deleted
import bernard.edited
import bernard.invites
import bernard.housekeeping
import bernard.regulator

# Automoderation modules
import bernard.automod_gamerwords

#background jobs
import bernard.scheduler
import bernard.remind

logger.warn("STARTING DISCORD BOT...")
bernard.discord.bot.run(bernard.config.cfg['discord']['token'])
