#!/usr/bin/env python3

'''
TODO:
    Add CTFd support
    - Add challenges automatically (with descriptions and files links)
    - Submit flags through bot
    - A local CTFd postion shower of our team and points
'''

# Library imports
import mysql.connector
import discord
import requests
import dateparser
import datetime
import string
import json
import typing
import traceback
import logging

from discord import CategoryChannel, errors
from discord.ext import tasks, commands
from mysql.connector import errorcode

# Stuff for debugging
DEBUG_SQL = True
BOT_DEBUG = False

# Variable declarations
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0',
}

pref = '+' if BOT_DEBUG else '-'
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
client = commands.Bot(command_prefix = pref,intents = intents)
client.remove_command('help')

# General variables
charset = string.ascii_letters + string.digits + " -_"


# SQL Connection Database.
def connect_sql():
    global db, mycursor
    db = mysql.connector.connect(
        host="db",
        user="ctf",
        passwd="ctf",
        database="ctf",
        auth_plugin='mysql_native_password',
    )

    mycursor = db.cursor()

# Functions - General
def read_token():
    with open("token.txt","r") as f:
        lines = f.readlines()
        return lines[0].strip()

connect_sql()
token = read_token()

def log(*args):

    result = ' '.join([x if isinstance(x, str) else str(x) for x in args])

    logger.error(result)

def run_sql_statement(statement, *args, **kwargs):
    try:
        if DEBUG_SQL:
            log("Executing SQL:", statement)

        mycursor.execute(statement, *args, **kwargs)
        return True

    except mysql.connector.Error as e:
        log("Original exception:", e)
        if e.errno == errorcode.ER_NO_SUCH_TABLE:
            log("Exception: No such table")

        elif e.errno == errorcode.ER_CLIENT_INTERACTION_TIMEOUT:
            log("MYSQL Connection timed out")
            connect_sql()
            log("Connection established again")
            log("Retrying last execution")
            return run_sql_statement(statement, *args, **kwargs)

        else:
            log("Exception", e, "raised")
        
        return False

def run_sql_with_commit(statement, *args, **kwargs):
    try:
        if DEBUG_SQL:
            log("Executing SQL:", statement)

        mycursor.execute(statement, *args, **kwargs)
        db.commit()
        return True

    except mysql.connector.Error as e:
        log("Original exception:", e)
        if e.errno == errorcode.ER_NO_SUCH_TABLE:
            log("Exception: No such table")

        elif e.errno == errorcode.ER_CLIENT_INTERACTION_TIMEOUT:
            log("MYSQL Connection timed out")
            connect_sql()
            log("Connection established again")
            log("Retrying last execution")
            return run_sql_with_commit(statement, *args, **kwargs)

        else:
            log("Exception", e, "raised")
        
        return False

def get_name(ctx, id_: int):
    ret = ctx.guild.get_member(id_)

    if not ret:
        ret = client.get_user(id_)

    if not ret:
        ret = 'Deleted User'
    else:
        ret = ret.name

    return ret

def get_names(ctx, ids: list):
    names = []
    for _id in ids:
        names.append(get_name(ctx, _id))

    return names

def unroll_list_of_names(contribs: list):
    if len(contribs) == 1:
        return contribs[0]
    
    else:
        return ', '.join(contribs[:-1]) + " and " + contribs[-1]

def normalize_name(name):
    ret = name.replace(" ", '-')

    for char in name:
        if char not in charset:
            ret = ret.replace(char, "-")
    
    ret = ret.strip("-")

    return ret

def table_exists(table_name):
    run_sql_statement(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'ctf' AND table_name = '{table_name}'")
    return bool(next(mycursor)[0])

def challenge_exists(chall: discord.TextChannel):
    if run_sql_statement(f"SELECT COUNT(*) FROM `{chall.category.id}` WHERE challenge = {chall.id}"):
        return next(mycursor)[0] == 1
    else:
        return False

# Helper Functions
async def error_log(ctx, *error_strings):
    error_string = ' '.join([x if isinstance(x, str) else str(x) for x in error_strings ])
    log(error_string)
    await ctx.send(embed = discord.Embed(title = "", description = error_string, color = 0xff0000))

async def success_msg(ctx, *msg_strings):
    msg_string = ' '.join([x if isinstance(x, str) else str(x) for x in msg_strings ])
    log(msg_string)
    await ctx.send(embed = discord.Embed(title = "", description = msg_string, color = 0x00ff00))

@client.event
async def on_ready():
    await client.change_presence(status = discord.Status.idle, activity = discord.Game(f'Listening to {pref}'))
    log("Ready")

# Bot Commands
@client.command()
async def help(ctx):
    msg = '''**COMMANDS:**```
addchall - adds the challenge you name [-addchall challname]
addsolve/addsolv/adsol/as - adds a challenge and marks it solved [-as challname]
    Especially for @vishiwoz
all      - shows all the solved challenges [-all]
clean    - obviously cleans the messages [-clean amount]
create   - create a new CTF to win [-create ctfname]
help     - Shows this message [-help]
over     - mark the ctf over once the ctf is over [-over]
solved   - mark the challenge solved, it has different options
    - In challenge channel:
        -solved [@contributor, ...]
    - From anywhere else:
        -solved #chall-name [@contributor, ...]
setcreds - set creds [-setcreds url login password]
join     - join a ctf the team is playing [-join ctfname]```'''
    await ctx.send(msg)

@client.command()
async def join(ctx, *, role):
    if ctx.channel.name == "joinctf":
        member = ctx.message.author 
        role_obj = discord.utils.get(ctx.guild.roles, name = role)

        if role_obj:
            await member.add_roles(role_obj)
            await ctx.message.add_reaction('✅')
        
        else:
            await error_log(ctx, f"There's no role named '{role}'")
        
    else:
        await ctx.send("```use this in joinctf channel please !```")

@client.command()
@commands.has_guild_permissions(administrator = True)
async def deletectf(ctx, *, category: CategoryChannel):
    channels = category.channels
    for i in channels:
        if i.name != "main":
            await i.delete()

@client.command(usage = 'Need ctf name. Type `-help` to see usage', aliases = ["newctf", "createctf"])
@commands.has_guild_permissions(administrator = True)
async def create(ctx, *, ctfname):
    if ctx.channel.name == "_bot_query":
        ctfname = normalize_name(ctfname)
        role = await ctx.guild.create_role(name = ctfname)
        category_object = await ctx.guild.create_category(ctfname)
        main_channel = await ctx.guild.create_text_channel("main", category = category_object, sync_permission = True)

        await category_object.set_permissions(role, read_messages = True, send_messages = True, connect = True, speak = True)
        await category_object.set_permissions(ctx.guild.default_role, read_messages = False, connect = False)

        if not run_sql_statement(f"CREATE TABLE `{category_object.id}` (challenge BIGINT UNSIGNED, solved boolean not null default 0, contributors JSON, misc JSON)"):
            await error_log(ctx, "Failed to create SQL table")
            return
        
        ctf_info = {"name": ctfname, "role": role.id, "main": main_channel.id, "category": category_object.id}
        
        run_sql_with_commit(f"INSERT INTO `{category_object.id}` (challenge, solved, contributors, misc) VALUES (1337, 0, '{json.dumps([])}', '{json.dumps(ctf_info)}')")

        await success_msg(ctx, f"Kill the CTF. Channel created {ctfname}")
    else:
        await ctx.send("Go to Bot Query !")

@client.command(aliases = ["add"])
async def addchall(ctx, *, challname):

    if ctx.channel.name == 'main':
        challname = normalize_name(challname)
        category_object = ctx.channel.category

        channel = await ctx.guild.create_text_channel(challname, category = category_object, sync_permission = True)

        await success_msg(ctx, f"New Challenge - {challname}.")

        chall_info = {"name": challname}

        if not run_sql_with_commit(f"INSERT INTO `{category_object.id}` (challenge, solved, contributors, misc) VALUES ({channel.id}, 0, '{json.dumps([])}', '{json.dumps(chall_info)}')"):
            if not table_exists(category_object.id):
                await error_log(ctx, f"No table for {category_object.name} ctf.")
        
        return channel

    else:
        await ctx.send("Go to main channel to create challenges.")

@client.command(aliases = ["solve", "sol"])
async def solved(ctx, source_channel: typing.Optional[discord.TextChannel], contributors: discord.ext.commands.Greedy[discord.User] = [], *args):

    if source_channel:
        channel = source_channel
    else:
        channel = ctx.channel
    
    if ctx.author not in contributors:
        contributors.append(ctx.author)

    if channel.name == 'main':
        await error_log(ctx, "Not Sure if main is solvable.")
        return 0

    if not challenge_exists(channel):
        if not table_exists(channel.category.id):
            await error_log(ctx, "The channel doesn't belong to an active CTF category")
            return 0
        
        await error_log(ctx, f"No entry for {channel.name} in {channel.category.name} Table. Maybe it was added manually.")
        return 0

    category = channel.category
    contribs = [user.id for user in contributors]

    if run_sql_statement(f"SELECT solved, contributors FROM `{category.id}` WHERE challenge = {channel.id}"):
        result = next(mycursor)
        solved = bool(result[0])
        sql_contributors = set(json.loads(result[1]))
        local_contribs = set(contribs)

        if solved:
            if ctx.author.id in sql_contributors:
                if not local_contribs.issubset(sql_contributors):
                    sql_contributors.update(local_contribs)

                    if run_sql_with_commit(f"UPDATE `{category.id}` SET contributors = '{json.dumps(list(sql_contributors))}' WHERE challenge = {channel.id}"):
                        await success_msg(ctx, "Updated contributors list succesfully")
                    else:
                        await error_log(ctx, "Something went wrong while updating contributors list")

                    return 0
                else:
                    await error_log(ctx, "Bruh, You drunk? You're trying to solve an already solved challenge")
                    return 0
            else:
                await error_log(ctx, "You cannot update contributors list because you're not one of them")
                return 0

    run_sql_with_commit(f"UPDATE `{category.id}` SET solved = '1', contributors = '{json.dumps(contribs)}' WHERE challenge = {channel.id}")

    await success_msg(ctx, f"Amazing Work Hacker. {channel.name} solved.")
    await channel.edit(name=f"solved-{channel.name}")

    if ctx.channel.name != "main": await success_msg(discord.utils.get(category.text_channels, name = "main"), f"{unroll_list_of_names([x.name for x in contributors])} solved {channel.name[7:]}.")

@client.command(aliases = ["addsolve", "adsol", "addsolv", "as"])
async def addsolved(ctx, *, challname):
    if ctx.channel.name == "main":
        channel = await addchall(ctx, challname = challname)
        await solved(ctx, channel)
        await channel.send(embed = discord.Embed(title = "", description = f"Solved by {ctx.author.name}"))
    else:
        await error_log(ctx, "Please go to main channel")

@client.command()
async def setcreds(ctx, *args):
    url, login, password = args

    msg = await ctx.send(f"link: {url}\n```Login: {login}\nPassword: {password}```")
    await msg.pin()

@client.command()
async def all(ctx):
    if ctx.channel.name == "main":
        category_object = ctx.channel.category

        if not run_sql_statement(f"SELECT * from `{category_object.id}`"):
            if not table_exists(category_object.id):
                await error_log(ctx, "Table doesn't exist")
                return 0

        lines = []

        for x in mycursor:
            log("RESULT:", x)
            if x[1] == 1:
                x = [x[0], x[1], json.loads(x[2]), json.loads(x[3])]
                # users = unroll_list_of_names([ctx.guild.get_member(i).name for i in x[2]])
                users = unroll_list_of_names(get_names(ctx, x[2]))

                lines.append(f"{x[3]['name']} solved by {users}")

        if len(lines) > 0:
            embedVar = discord.Embed(title = ":triangular_flag_on_post: Solved Challenges:", description = '\n'.join(lines))
            await ctx.send(embed = embedVar)
        
        else:
            await ctx.send("No challenges have been solved yet.")

@client.command()
@commands.has_guild_permissions(administrator = True)
async def over(ctx):
    if ctx.channel.name == "main":
        category_object = ctx.channel.category
        channels = category_object.channels


        if table_exists(category_object.id):
            await ctx.send("Kuddos to everyone who fought hard.")
            await all(ctx)

            run_sql_statement(f"SELECT misc FROM `{category_object.id}` WHERE challenge = 1337")
            ctf_info = json.loads(next(mycursor)[0])

            role = discord.utils.get(ctx.guild.roles, id = ctf_info['role'])

            run_sql_with_commit(f"DROP TABLE `{category_object.id}`")
            await role.delete()

            for i in channels:
                await i.set_permissions(ctx.guild.default_role, send_messages = True, read_messages = True)
        else:
            await error_log(ctx, "Weirdly table doesn't exists")
    
    else:
        await error_log(ctx, "Please go to main channel.")

# Extra Utilities
IST = datetime.timedelta(hours = 5, minutes = 30)

@client.command()
async def upcoming(ctx, *args):
    linkupcoming = "https://ctftime.org/api/v1/events/"

    N = 3
    if args and args[0].isdigit():
        N = int(args[0])

    r = requests.get(linkupcoming, headers = headers, params = str(N))
    upcoming_data = r.json()
    data = []

    for ctf in range(len(upcoming_data)):
        ctf_title = upcoming_data[ctf]["title"]
        ctf_start = dateparser.parse(upcoming_data[ctf]["start"])
        ctf_end = dateparser.parse(upcoming_data[ctf]["finish"])
        ctf_start = ctf_start + IST
        ctf_end = ctf_end + IST
        ctf_start = ctf_start.strftime('%a %b %d, %Y %I:%M:%S %p')
        ctf_end = ctf_end.strftime('%a %b %d, %Y %I:%M:%S %p')

        # (ctf_start, ctf_end) = (upcoming_data[ctf]["start"].replace("T", " ").split("+", 1)[0] + " UTC", upcoming_data[ctf]["finish"].replace("T", " ").split("+", 1)[0] + " UTC")
        # (ctf_start, ctf_end) = (re.sub(":00 ", " ", ctf_start), re.sub(":00 ", " ", ctf_end))
        dur_dict = upcoming_data[ctf]["duration"]
        ctf_weight = float(upcoming_data[ctf]['weight'])
        (ctf_hours, ctf_days) = (str(dur_dict["hours"]), str(dur_dict["days"]))
        ctf_link = upcoming_data[ctf]["url"]
        ctf_image = upcoming_data[ctf]["logo"]
        ctf_format = upcoming_data[ctf]["format"]
        ctf_place = ["Online", "Onsite"][int(upcoming_data[ctf]["onsite"])]
        # if ctf_place == False:
        #     ctf_place = "Online"
        # else:
        #     ctf_place = "Onsite"

        embed = discord.Embed(title = ctf_title, description = ctf_link, color = int("ffffff", 16))
        if ctf_image != '':
            embed.set_thumbnail(url = ctf_image)
        else:
            embed.set_thumbnail(url = 'https://ctftime.org/static/images/ct/logo.svg')

        embed.add_field(name = 'Weight', value = str(ctf_weight), inline = True)
        embed.add_field(name = "Duration", value = ((ctf_days + " days, ") + ctf_hours) + " hours", inline = True)
        embed.add_field(name = "Format", value = (ctf_place + " ") + ctf_format, inline = True)
        embed.add_field(name = "Timeframe", value = (ctf_start + " -> ") + ctf_end, inline = True)
        # await ctx.channel.send(embed=embed)
        data.append([ctf_weight, embed])
    
    data.sort(key=lambda i: i[0], reverse = True)
    for i in data[:N]:
        await ctx.channel.send(embed=i[1])

@client.command()
async def clean(ctx, amount = 5):
    await ctx.channel.purge(limit = amount)

if BOT_DEBUG:
    @client.command()
    async def test(ctx, *args):
        log(ctx, dir(ctx), ctx.author)
        log(*args)

@client.event
async def on_command_error(ctx, error):
    orig = getattr(error, "original", None)
    log("Discord Error:", error, type(error), type(orig))
    log("Command:", ctx.command)
    traceback.print_exception(type(error), error, error.__traceback__)

    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Invalid command. See `-help`")
    
    elif isinstance(error, commands.errors.CommandInvokeError):
        if isinstance(orig, errors.Forbidden):
            await error_log(ctx, "Error:", orig.text)

    elif isinstance(error, commands.errors.MissingPermissions):
        await error_log(ctx, f"You don't have {unroll_list_of_names(error.missing_perms)} permission(s)")
    
    elif isinstance(error, commands.errors.BotMissingPermissions):
        await error_log(ctx, f"Bot doesn't have {unroll_list_of_names(error.missing_perms)} permission(s)")

    else:
        await error_log(ctx, "Uncaught error:", error, type(error))

client.run(token)
<<<<<<< HEAD
=======

>>>>>>> c8ba4608d1cbfa8bccd692ecb98cf35ae855e1d0