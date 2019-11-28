from datetime import datetime, timedelta
from typing import Tuple

import discord
from discord.ext import commands

from db_classes.PGWarningDB import PGWarningDB
from config import warnings_config

import asyncio

from models.warnings_models import RefWarning

from utils import emoji
import logging

logger = logging.getLogger("Referee")


def get_warned_color(color: tuple) -> tuple:
    def is_grey(c):
        return max([abs(c[0] - c[1]), abs(c[1] - c[2]), abs(c[0] - c[2])]) < 25

    new_color = (color[0] // 2, color[1] // 2, color[2] // 2)
    if sum(new_color) / 3 < 100 and is_grey(new_color):
        return warnings_config.default_warned_color
    else:
        return new_color


class Warnings(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = PGWarningDB()
        self.latest_warning_mod_id = None
        self.moderators = list()
        self.guild: discord.Guild = None  # initialized in on_ready

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.loop.create_task(self.bg_check())
        self.guild = self.bot.guilds[0]

    async def bg_check(self):
        """
        Runs every 120 seconds to check whether warnings have expired
        """
        while not self.bot.is_ready():
            await asyncio.sleep(1)

        while not self.bot.is_closed():
            await self.check_all_members()
            await asyncio.sleep(120)  # task runs every second minute

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Called by api whenever a message is received.
        Checks for warnings and clears
        """
        if not message.guild:
            return
        elif not self.moderators:
            self.moderators = list(
                filter(lambda m: message.channel.permissions_for(message.author).kick_members, self.guild.members)
            )
        if message.author in self.moderators:
            if message.content.startswith("?warn "):
                logger.info(f"Identified warn command: '{message.content}' from "
                            f"{message.author.name}#{message.author.discriminator}")
                self.latest_warning_mod_id = message.author.id

        if self.message_is_warning(message):
            name, reason = self.get_name_reason(message)
            logger.info(f"Identified warning: '{message.content}'. {name}, {reason}")

            member: discord.Member = await commands.MemberConverter().convert(await self.bot.get_context(message), name)

            if self.latest_warning_mod_id:
                mod: discord.User = await self.bot.fetch_user(self.latest_warning_mod_id)
            else:
                mod = None

            warning = RefWarning(user_id=member.id,
                                 reason=reason,
                                 timestamp=message.created_at,
                                 mod_name=f"{mod.display_name}#{mod.discriminator}" if mod else None,
                                 expiration_time=message.created_at + timedelta(hours=warnings_config.warning_lifetime))

            await self.db.put_warning(warning)
            await self.enforce_punishments(await self.bot.get_context(message), member, warning)

        # Else, if the message is a clear
        elif self.message_is_clear(message):
            logger.info(f"Identified clear: '{message.content}'")

            name = self.clean_content(message)[:-1].split("for ")[-1]
            member: discord.Member = await commands.MemberConverter().convert(await self.bot.get_context(message), name)

            await self.db.expire_warnings(member.id)
            await self.remove_warned_roles(member)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Checks on each join to make sure that members can't get rid of the warned role by leaving and rejoining
        """
        await self.check_warnings(member)

    @staticmethod
    def clean_content(message: discord.message) -> str:
        """
        Should be replaced by new discordpy util function
        """
        content = message.clean_content
        content = content.replace("***", "").replace("\\_", "_").replace("\\*", "*").replace("\\\\", "\\")
        return content

    def message_is_warning(self, message: discord.message) -> bool:
        """
        Checks whether a message is a warning confirmation from Dyno.
        This could break at any time, since Dynos code could be changed without warning
        """
        logger.debug(f"Checking message {message.content} from {message.author.name}")
        content = self.clean_content(message)
        if message.author.id == warnings_config.dyno_id:
            if "has been warned" in content:
                return True
            elif "They were not warned" in content:
                return True
        return False

    @staticmethod
    def get_warned_roles(member: discord.Member) -> list:
        """
        Filters through a members roles to return only the ones related to warning
        """
        warned_roles = list(filter(lambda r: r.name == warnings_config.warned_role_name, member.roles))
        return warned_roles

    def get_name_reason(self, message: discord.message) -> Tuple[str, str]:
        """
        Parses a warning confirmation for name and reason
        """
        content = self.clean_content(message)
        if "has been warned." in content:
            name, reason = content.split(" has been warned.", 1)
            name = name.split("> ")[1]
        elif "They were not warned" in content:
            name, reason = content.split(". They were not warned.", 1)
            name = name.split("Warning logged for ")[1]
        else:
            raise RuntimeError(f"'{content}' logged as warning, but can not be parsed")
        reason = reason.replace(", ", "", 1)
        return name, reason

    def message_is_clear(self, message: discord.message):
        """
        Checks whether a message is a "warnings cleared" confirmation from Dyno
        """
        content = self.clean_content(message)
        return "<:dynoSuccess:314691591484866560> Cleared" in content and "warnings for " in content

    async def acknowledge(self, message: discord.Message):
        """
        Briefly adds an emoji to a message
        """
        await message.add_reaction(emoji.eye)
        await asyncio.sleep(1)
        await message.remove_reaction(emoji.eye, self.bot.user)

    # noinspection PyUnusedLocal
    async def enforce_punishments(self, ctx: commands.Context, member: discord.Member, warning: RefWarning):
        """
        This method checks a users number of active warnings and enacts the punishments

        """
        await self.check_warnings(member)
        num_warnings = len(await self.db.get_active_warnings(member.id))
        if num_warnings > 1:
            await ctx.channel.send(
                f"{member.display_name} has been warned {num_warnings}"
                f" times in the last {warnings_config.warning_lifetime} hours."
                f"Automatically muting them for {4**(num_warnings-1)} hours",
                delete_after=30
            )
            await self.mute(member, 4**(num_warnings - 1) * 60 * 60)

    async def check_warnings(self, member: discord.Member):
        """
        This method compares a users roles to the status in the db and marks or unmarks them as warned
        """
        is_warned = bool(self.get_warned_roles(member))

        active_warnings = await self.db.get_active_warnings(member.id)

        if active_warnings:
            if not is_warned:
                await self.assign_warned_role(member)
        elif is_warned:
            await self.remove_warned_roles(member)

    async def check_all_members(self):
        """
        Checks the warnings for all members in a guiöd
        """
        for member in self.guild.members:
            await self.check_warnings(member)

    async def assign_warned_role(self, member: discord.Member):
        """
        Assigns a "warned" role to a member, if possible, and if necessary
        """
        if member.top_role.position > member.guild.me.top_role.position:
            return

        if self.get_warned_roles(member):
            return

        warning_color = discord.Colour.from_rgb(*get_warned_color(member.colour.to_rgb()))
        warned_roles = list(
            filter(lambda r: r.name == warnings_config.warned_role_name and r.colour == warning_color, self.guild.roles))

        if not warned_roles:
            role = await self.guild.create_role(name=warnings_config.warned_role_name,
                                           colour=warning_color)
            await asyncio.sleep(0.5)
        else:
            role = warned_roles[0]

        if role.position <= member.top_role.position:
            await role.edit(position=max(member.top_role.position, 1))

        await member.add_roles(role)

    async def remove_warned_roles(self, member: discord.Member):
        """
        Removes all "warned" roles from a member
        """
        warned_roles = self.get_warned_roles(member)
        await member.remove_roles(*warned_roles)

    @staticmethod
    async def mute(member: discord.Member, mute_time_seconds: int):
        """
        Mutes a member for a certain timespan
        """
        muted_roles = discord.utils.get(member.guild.roles, name="Muted")
        if isinstance(muted_roles, list):
            muted_roles = muted_roles[0]
        await member.add_roles(muted_roles)
        await asyncio.sleep(mute_time_seconds)
        await member.remove_roles(*muted_roles)

    async def warning_str(self, warning: RefWarning, show_expiration: bool = False, show_warned_name: bool = False) -> str:
        """
        Returns information about a warning in a nice format
        """
        warn_str = ""
        if show_warned_name:
            user: discord.User = await self.bot.fetch_user(warning.user_id)
            name = f"{user.name}#{user.discriminator}" if user else f"Not found({warning.user_id})"
            warn_str += f"**User:** {name}\n"
        warn_str += f"**Date:** {warning.date_str}\n"
        if show_expiration:
            warn_str += f"**Expires**: {warning.expiration_str}\n"
        warn_str += f"**Reason:** {warning.reason}\n"
        warn_str += f"**Mod:** {warning.mod_name}\n"
        return warn_str

    @commands.command(name="warn")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        """
        Adds a new warning for a member.
        Usage: ref!warn @Member [reason for the warning]
        """
        warning = RefWarning(
            user_id=member.id,
            reason=reason,
            timestamp=datetime.now(),
            mod_name=f"{ctx.author.display_name}#{ctx.author.discriminator}",
            expiration_time=datetime.now() + timedelta(hours=warnings_config.warning_lifetime))
        await self.db.put_warning(warning)
        await self.enforce_punishments(ctx, member, warning)
        await self.acknowledge(ctx.message)

    @commands.command(name="clear")
    @commands.has_permissions(kick_members=True)
    async def clear(self, ctx: commands.Context, member: discord.Member):
        """
        Removes all active warnings from a member. The warnings persist in an expired state.
        """
        await self.db.expire_warnings(member.id)
        await self.remove_warned_roles(member)
        await self.acknowledge(ctx.message)

    @commands.command(aliases=["warns", "?"])
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member = None):
        """
        Lists all active and expired warnings for member
        """
        if not member:
            await ctx.send("Usage: `ref!warnings @member`", delete_after=30)
            return

        all_warnings = await self.db.get_warnings(member.id)
        active_warnings = await self.db.get_active_warnings(member.id)
        expired_warnings = list(filter(lambda x: x not in active_warnings, all_warnings))

        if all_warnings:
            title = "{}: {} warnings ({} active)".format(member.display_name, len(all_warnings), len(active_warnings))
        else:
            title = f"No warnings for {member.display_name}#{member.discriminator}"
        embed = discord.Embed(title=title, color=discord.Color.dark_gold())

        if active_warnings:
            active_str = "\n".join(await self.warning_str(w, show_expiration=True) for w in active_warnings)
            embed.add_field(name="Active ({})".format(len(active_warnings)), value=active_str, inline=False)

        if expired_warnings:
            expired_str = "\n".join(await self.warning_str(w) for w in expired_warnings)
            embed.add_field(name="Expired ({})".format(len(all_warnings) - len(active_warnings)), value=expired_str,
                            inline=False)

        await ctx.send(embed=embed)

    @commands.command(aliases=["active", "!"])
    @commands.has_permissions(kick_members=True)
    async def active_warnings(self, ctx: commands.Context):
        """
        Lists all currently active warnings
        """
        active_warnings = await self.db.get_all_active_warnings()

        title = "Active warnings" if active_warnings else "No active warnings"
        embed = discord.Embed(title=title, color=discord.Color.dark_gold())

        for member_id in active_warnings:
            warnings = await self.db.get_active_warnings(member_id)
            active_str = "\n".join([await self.warning_str(w, show_warned_name=True, show_expiration=True) for w in warnings])
            if active_str:
                embed.add_field(name=ctx.guild.get_member(member_id), value=active_str, inline=False)

        await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Warnings(bot))
