import patreon
import discord
from typing import Union


def get_campaign_id(client: patreon.API, guild: discord.Guild) -> int:
    """
    Gets Patreon campaign ID assoicated with this guild

    Returns:
        int: Campaign ID assigned to this guild in Patreon
    """
    campaigns = client.get_campaigns(
        100,
        includes=None,
        fields={"campaign": ["discord_server_id"]},
    ).data()

    campaign_id = None
    for c in campaigns:
        discord_server_id = c.attribute("discord_server_id")
        if discord_server_id is not None and guild.id == int(discord_server_id):
            campaign_id = int(c.id())
            break

    return campaign_id


def get_tier_data(client: patreon.API, campaign_id: int):
    tiers = client.get_campaigns_by_id(campaign_id, includes=["tiers"], fields={"tier": ["amount_cents"]}).data()
    return tiers.relationship("tiers")


def get_patreon_member_id_all(client: patreon.API, campaign_id: int) -> dict:
    """

    Args:
        client (patreon.API): _description_
        campaign_id (int): _description_

    Returns:
        dict: _description_
    """
    patreon_users = client.get_campaigns_by_id_members(
        campaign_id,
        10000000,
        cursor=None,
        includes=["user"],
        fields={"user": ["social_connections"]},
    ).data()

    ids = {}
    for p in patreon_users:
        print(p.json_data)
        discord_data = p.relationship("user").attribute("social_connections").get("discord", {})
        print(p.relationship("user").attribute("social_connections"))
        discord_id = discord_data.get("user_id", None) if discord_data is not None else None
        if discord_id is not None:
            ids[int(discord_id)] = p.id()

    return ids


def get_patreon_member_id(client: patreon.API, campaign_id: int, member: discord.Member) -> str:
    """


    Args:
        client (patreon.API): _description_
        member (discord.Member): _description_

    Returns:
        str: _description_
    """

    return get_patreon_member_id_all(client, campaign_id).get(member.id, None)


def get_member_info(client: patreon.API, campaign_id: int, member: Union[discord.Member, str]):
    """


    Args:
        client (patreon.API): _description_
        campaign_id (int): _description_
        member (Union[discord.Member, str]): _description_
    """
    if isinstance(member, discord.Member):
        patreon_id = get_patreon_member_id(client, campaign_id, member)
    else:
        patreon_id = member

    patreon_user = client.get_members_by_id(
        patreon_id,
        includes=["currently_entitled_tiers"],
        fields={
            "member": [
                "next_charge_date",
                "campaign_lifetime_support_cents",
                "last_charge_date",
                "patron_status",
                "pledge_relationship_start",
                "will_pay_amount_cents",
            ]
        },
    ).data()

    return patreon_user


def get_pledge_history(client: patreon.API, campaign_id: int, member: Union[discord.Member, str]) -> list:
    """


    Args:
        client (patreon.API): _description_
        member (discord.Member): _description_
    """
    if isinstance(member, discord.Member):
        patreon_id = get_patreon_member_id(client, campaign_id, member)
    else:
        patreon_id = member

    patreon_user = client.get_members_by_id(patreon_id, includes=["pledge_history"]).data()

    pledges = list(patreon_user.relationship("pledge_history"))
    pledges.reverse()
    return pledges
