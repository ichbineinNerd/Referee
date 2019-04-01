import asyncio

import discord
from discord.ext import commands
import timeit
from config import config

import os
import sys
import logging
import logging.handlers


bot = commands.Bot(command_prefix=config.commandPrefixes,
                   case_insensitive=True,
                   pm_help=None,
                   activity=discord.Game(name=config.status))


def setup_logger():

    if not os.path.exists("logs"):
        print("Creating logs folder...")
        os.makedirs("logs")

    logger = logging.getLogger("Referee")
    logger.setLevel(logging.INFO)

    ref_format = logging.Formatter(
        '%(asctime)s %(levelname)s %(filename)s:%(funcName)s:%(lineno)d: '
        '%(message)s',
        datefmt="[%d/%m/%Y %H:%M]")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(ref_format)

    fhandler = logging.handlers.RotatingFileHandler(
        filename='logs/ref.log', encoding='utf-8', mode='a',
        maxBytes=10 ** 7, backupCount=5)
    fhandler.setFormatter(ref_format)

    logger.addHandler(fhandler)
    logger.addHandler(stdout_handler)
    return logger


def main():
    """
    Main function, loads extension and starts the bot
    """
    for ext in config.extensions:
        bot.load_extension(f"extensions.{ext}")
        logger.info(f"Loaded {ext}")

    bot.run(config.token)


@bot.event
async def on_ready():
    """
    On_ready eventhandler, gets called by api
    """
    logger.info("Ready!")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    logger.error(error)


@bot.command()
async def ping(ctx: commands.Context):
    """
    Basic command to check whether bot is alive

    :param ctx: Context object for the specific invoked ćommands
    """
    start = timeit.default_timer()
    title = "Pong. "
    embed = discord.Embed(title=title, color=discord.Color.dark_gold())
    msg = await ctx.send(embed=embed)  # type: discord.Message
    zoop = discord.utils.get(ctx.guild.emojis, name="zoop")
    dur = timeit.default_timer() - start
    embed.title += f"  |  {dur:.3}s"
    await msg.edit(embed=embed)
    await msg.add_reaction(zoop)

    def check(reaction, user):
        return user == ctx.author and reaction.emoji == zoop

    try:
        await bot.wait_for("reaction_add", check=check, timeout=120)
    except asyncio.TimeoutError:
        pass
    await msg.delete()
    await ctx.message.delete()


# noinspection PyUnusedLocal
@bot.command(aliases=["game"])
@commands.has_permissions(kick_members=True)
async def activity(ctx: commands.Context, *, activity: str):
    """
    Changes the bots current discord activity
    :param ctx: Context object for the specific invoked ćommands
    :param activity: The string that will be displayed as activity
    """
    await bot.change_presence(activity=discord.Game(name=activity))

if __name__ == '__main__':
    logger: logging.Logger = setup_logger()
    main()
