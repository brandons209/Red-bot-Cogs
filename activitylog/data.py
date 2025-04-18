# plotting

import pandas as pd
import numpy as np
import networkx as nx
import pandas as pd
import discord

import matplotlib.pyplot as plt
from matplotlib.dates import AutoDateLocator, DateFormatter

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Union, Tuple
from io import BytesIO


def set_date_axis_format(ax, period: int, rotation: int = 45):
    """
    Applies automatic date locator with fixed date formatting to a matplotlib axis.

    Args:
        ax (plt.Axes): The axis to format.
        rotation (int): Rotation angle for the x-axis date labels.
    """
    locator = AutoDateLocator()

    if period < 2:
        formatter = DateFormatter("%Y-%m-%d %H:%M")  # Detailed if short
    elif period < 60:
        formatter = DateFormatter("%Y-%m-%d")  # Normal
    else:
        formatter = DateFormatter("%Y-%m")

    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    plt.setp(ax.get_xticklabels(), rotation=rotation)


def plot_retention(members: List[discord.Member]):
    """
    _summary_

    Args:
        members (List[discord.Member]): _description_

    Returns:
        _type_: _description_
    """
    data: Dict[str, int] = {}
    now = discord.utils.utcnow()
    for member in members:
        since_joined = (now - member.joined_at).days
        data[member.display_name] = since_joined
    df = pd.DataFrame(data={"display name": data.keys(), "days in server": data.values()}).set_index("display name")

    # make graph and send it
    fontsize = 30
    fig = plt.figure(figsize=(50, 30))
    ax = plt.axes()

    max_days = df["days in server"].max()

    if max_days > 730:  # > 2 years
        df["years in server"] = df["days in server"] / 365
        col = "years in server"
        bin_size = 0.25  # 1/4 year
        max_days = df[col].max()
        xlabel = "Time in Server (Quarters)"
        label_format = lambda x: f"{x:.1f}y"
    elif max_days > 365:  # > 1 year
        bin_size = 60  # bimonthly
        xlabel = "Time in Server (2-Month Intervals)"
        label_format = lambda x: f"{x/30:.1f}m"
        col = "days in server"
    else:
        bin_size = 30  # monthly
        xlabel = "Time in Server (Months)"
        label_format = lambda x: f"{x/30:.0f}m"
        col = "days in server"

    # Build bins
    num_bins = int(max_days // bin_size) + 1
    bins = np.linspace(0, bin_size * num_bins, num_bins + 1)

    hist = ax.hist(df[col], bins=bins, rwidth=0.5)
    for i in range(len(bins) - 1):
        ax.text(hist[1][i], hist[0][i], str(int(hist[0][i])), fontsize=fontsize)

    # make graph look nice
    plt.title(
        f"Member retention of all members in {members[0].guild.name}",
        fontsize=fontsize,
    )
    plt.xlabel(xlabel, fontsize=fontsize)
    plt.ylabel("# of members", fontsize=fontsize)
    plt.xticks(bins, [label_format(b) for b in bins], fontsize=fontsize)
    plt.yticks(fontsize=fontsize)
    plt.grid(True)
    fig.tight_layout()

    data_file = BytesIO()
    figure_file = BytesIO()

    df.to_csv(data_file, index=True)
    fig.savefig(figure_file, dpi=fig.dpi)
    figure_file.seek(0)
    data_file.seek(0)
    plt.close()

    return data_file, figure_file


def plot_hourly_heatmap(
    messages: List[Dict],
    channel_or_guild: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.Guild],
):
    """
    Plots a heatmap of message activity by day of week and hour of day.

    Args:
        messages (List[Dict]): List of message dicts with 'datetime'.
    """
    if not messages:
        return None, None

    # Prepare DataFrame
    df = pd.DataFrame(messages)
    df["hour"] = df["datetime"].dt.hour
    df["weekday"] = df["datetime"].dt.dayofweek  # Monday=0, Sunday=6
    if not df.empty:
        start_datetime = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

    # Pivot table: rows = hours, columns = weekdays
    pivot = df.groupby(["hour", "weekday"]).size().unstack(fill_value=0)

    # Ensure all hours and weekdays are present
    pivot = pivot.reindex(index=range(24), columns=range(7), fill_value=0)

    # Labels
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = [f"{h:02d}:00" for h in range(24)]

    data_file = BytesIO()
    figure_file = BytesIO()

    pivot.to_csv(data_file)
    data_file.seek(0)

    # Plot
    plt.figure(figsize=(10, 8))
    plt.imshow(pivot.values, aspect="auto", cmap="Blues", origin="lower")

    plt.xticks(ticks=range(7), labels=weekdays)
    plt.yticks(ticks=range(24), labels=hours)

    plt.xlabel("Day of Week")
    plt.ylabel("Hour of Day")
    plt.title(f"{channel_or_guild.name} Message Activity Heatmap since {start_datetime}")
    cbar = plt.colorbar()
    cbar.set_label("Number of Messages")

    plt.tight_layout()
    plt.savefig(figure_file)
    figure_file.seek(0)

    return data_file, figure_file


def plot_users_in_voice_channel(
    rows: List[Dict],
    bot,
    channel: Union[discord.VoiceChannel, discord.StageChannel],
    top_n_users: int = 10,
):
    """
    Plots time spent by each user in a specific voice channel.

    Args:
        rows (List[Dict]): List of voice state dicts (with join/move/leave).
        channel_id (int): Channel ID to analyze.
        top_n_users (int): Number of top users to display by time spent.
    """
    # Filter rows to relevant channel and related events
    df = pd.DataFrame(rows)
    # df["datetime"] = pd.to_datetime(df["datetime"])
    # df = df.sort_values("datetime").reset_index(drop=True)
    if not df.empty:
        start_datetime = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

    # Track session state per user
    time_spent = {}  # {user_id: total_seconds}
    user_session = {}  # {user_id: (start_time)}

    for _, row in df.iterrows():
        user_id = row["author_id"]
        action = row["action_type"]
        time = row["datetime"]

        if action == "join":
            user_session[user_id] = time

        elif action == "leave":
            start = user_session.pop(user_id, None)
            if start:
                delta = (time - start).total_seconds()
                time_spent[user_id] = time_spent.get(user_id, 0) + delta

        elif action == "move":
            # Leaving this channel
            start = user_session.pop(user_id, None)
            if start:
                delta = (time - start).total_seconds()
                time_spent[user_id] = time_spent.get(user_id, 0) + delta
            # Entering this channel
            if row["moved_to_id"] == channel.id:
                user_session[user_id] = time

    # Prepare DataFrame
    if not time_spent:
        return None, None

    user_ids = list(time_spent.keys())
    usernames = {}
    for i in range(len(user_ids)):
        user = channel.guild.get_member(user_ids[i]) or bot.get_user(user_ids[i])
        usernames[user_ids[i]] = user.display_name if user is not None else f"Unknown User {i+1}"

    data_file = BytesIO()
    df_plot = pd.DataFrame([{"User": usernames[user], "Minutes": seconds / 60} for user, seconds in time_spent.items()])
    df_plot.to_csv(data_file, index=False)
    data_file.seek(0)

    df_plot = df_plot.sort_values("Minutes", ascending=False).head(top_n_users)

    figure_file = BytesIO()

    # Plot
    plt.figure(figsize=(10, 6))
    plt.bar(df_plot["User"].astype(str), df_plot["Minutes"])
    plt.xlabel("User")
    plt.ylabel("Time Spent (minutes)")
    plt.title(f"Time Spent in Voice Channel {channel.name} since {start_datetime}")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(figure_file)
    figure_file.seek(0)

    return data_file, figure_file


def plot_voice_time_by_channel(rows: List[Dict[str, Any]], guild: discord.Guild, member: discord.Member):
    """
    Given voice activity rows (join, leave, move), calculates and plots
    time spent in each channel by the user.

    Assumes all rows come from a specific user

    Args:
        rows (List[Dict]): voice activity rows for a single user.
    """
    # Convert to DataFrame and sort chronologically
    df = pd.DataFrame(rows)
    # df["datetime"] = pd.to_datetime(df["datetime"])
    # df = df.sort_values("datetime")
    if not df.empty:
        start_datetime = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

    # Track sessions: {channel_id: total_seconds}
    time_spent = {}
    current_channel = None
    session_start = None

    for i, row in df.iterrows():
        event_time = row["datetime"]
        action = row["action_type"]
        channel_id = row["channel_id"]
        moved_to_id = row.get("moved_to_id")

        if action == "join":
            current_channel = channel_id
            session_start = event_time

        elif action == "leave":
            if current_channel and session_start:
                duration = (event_time - session_start).total_seconds()
                time_spent[current_channel] = time_spent.get(current_channel, 0) + duration
                current_channel = None
                session_start = None

        elif action == "move":
            # End current session
            if current_channel and session_start:
                duration = (event_time - session_start).total_seconds()
                time_spent[current_channel] = time_spent.get(current_channel, 0) + duration
            # Start new session
            current_channel = moved_to_id
            session_start = event_time

    # Build DataFrame for plotting
    if not time_spent:
        return None, None

    channel_ids = list(time_spent.keys())
    channel_names_ids = []
    for i in range(len(channel_ids)):
        channel = guild.get_channel(int(channel_ids[i]))
        channel_names_ids.append(channel.name if channel is not None else f"Unknown Channel {i+1}")
    minutes_spent = [time_spent[ch] / 60 for ch in channel_ids]

    plot_df = pd.DataFrame({"Channel Name": channel_names_ids, "Minutes Spent": minutes_spent})
    figure_file = BytesIO()
    data_file = BytesIO()

    plot_df.to_csv(data_file, index=False)
    data_file.seek(0)
    # Plot
    plt.figure(figsize=(10, 6))
    plt.bar(plot_df["Channel Name"].astype(str), plot_df["Minutes Spent"])
    plt.xlabel("Voice Channel Name")
    plt.ylabel("Time Spent (minutes)")
    plt.title(f"{member.display_name} Time Spent in Voice Channels since {start_datetime}")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(figure_file)
    figure_file.seek(0)

    return data_file, figure_file


def plot_text_activity_over_time(
    messages: List[Dict],
    guild: discord.Guild,
    member: Optional[discord.Member] = None,
    top_n_channels: int = 5,
    date_granularity: str = "D",
):
    """
    Plots a user's message activity over time, split by channel.

    Args:
        messages (List[Dict]): List of message dicts with 'channel_id' and 'datetime'.
        top_n_channels (int): Number of top channels (by message count) to include in plot.
        date_granularity (str): Date grouping: 'D' = daily, 'W' = weekly, etc.
    """
    if not messages:
        return None, None

    # Create DataFrame and preprocess
    df = pd.DataFrame(messages)
    # df["datetime"] = pd.to_datetime(df["datetime"])
    df["date_group"] = df["datetime"].dt.to_period(date_granularity).dt.to_timestamp()
    start_time = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

    # Count messages per date per channel
    grouped = df.groupby(["channel_id", "date_group"]).size().unstack(fill_value=0)

    # Get top N channels by total message count
    top_channels = grouped.sum(axis=1).nlargest(top_n_channels).index
    top_grouped = grouped.loc[top_channels]

    # Calculate total across all channels
    total_series = grouped.sum(axis=0)

    figure_file = BytesIO()
    data_file = BytesIO()

    # Plot
    plt.figure(figsize=(12, 6))
    names = {}
    for channel_id in top_grouped.index:
        c_or_t = guild.get_channel_or_thread(channel_id)
        if isinstance(c_or_t, discord.abc.GuildChannel):
            names[channel_id] = c_or_t.name
            label = f"C: {c_or_t.name}"
        elif isinstance(c_or_t, discord.Thread):
            names[channel_id] = c_or_t.name
            label = f"T: {c_or_t.name}"
        else:
            names[channel_id] = channel_id
            label = f"{int(channel_id)}"
        plt.plot(
            top_grouped.columns,
            top_grouped.loc[channel_id],
            label=label,
            marker="o",
        )

    plt.plot(total_series.index, total_series.values, label="Total", color="black", linewidth=2, linestyle="--")

    ax = plt.gca()
    date_range = (total_series.index[-1] - total_series.index[0]).days
    set_date_axis_format(ax, date_range)

    plt.xticks(rotation=45)
    plt.xlabel("Date")
    plt.ylabel("Messages Sent")
    if member:
        plt.title(f"{member.display_name} Message Activity by Channel Over Time since {start_time}")
    else:
        plt.title(f"Message Activity by Channel Over Time since {start_time}")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(figure_file)
    figure_file.seek(0)

    if member:
        df["author_id"] = member.display_name
    else:

        def rename(r):
            m = guild.get_member(r)
            return m.name if m else r

        df["author_id"] = df["author_id"].map(rename)

    df["channel_id"] = df["channel_id"].replace(names)

    df = df.rename({"author_id": "member", "channel_id": "channel"})
    df = df.set_index("datetime")

    df.to_csv(data_file, index=True)
    data_file.seek(0)

    return data_file, figure_file


def plot_guild_joins_and_leaves(audit_rows: List[Dict], date_granularity: str = "D"):
    """
    Plots server joins and leaves (including kicks and bans) over time.

    Args:
        audit_rows (List[Dict]): List of audit entries from the audit table.
        date_granularity (str): 'D' = day, 'W' = week, etc.
    """
    if not audit_rows:
        return None, None

    df = pd.DataFrame(audit_rows)
    # df["datetime"] = pd.to_datetime(df["datetime"])
    df["date_group"] = df["datetime"].dt.to_period(date_granularity).dt.to_timestamp()
    start_time = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

    # Define joins and leaves
    join_mask = df["action"] == "member_join"
    leave_mask = df["action"].isin(["member_leave", "kick", "ban"])

    joins = df[join_mask].groupby("date_group").size()
    leaves = df[leave_mask].groupby("date_group").size()

    # Combine into one DataFrame
    activity_df = pd.DataFrame({"Joins": joins, "Leaves": leaves}).fillna(0)

    activity_df["Net Change"] = activity_df["Joins"] - activity_df["Leaves"]

    # Plot
    plt.figure(figsize=(12, 6))
    plt.plot(activity_df.index, activity_df["Joins"], label="Joins", marker="o", color="green")
    plt.plot(activity_df.index, activity_df["Leaves"], label="Leaves", marker="o", color="red")
    plt.plot(
        activity_df.index,
        activity_df["Net Change"],
        label="Net Change",
        marker="o",
        linestyle="--",
        color="black",
    )

    ax = plt.gca()
    date_range = (df.iloc[-1]["datetime"] - df.iloc[0]["datetime"]).days
    set_date_axis_format(ax, date_range)

    data_file = BytesIO()
    figure_file = BytesIO()

    plt.xticks(rotation=45)
    plt.xlabel("Date")
    plt.ylabel("# joins/leaves")
    plt.title(f"Guild Joins and Leaves Over Time since {start_time}")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figure_file)
    figure_file.seek(0)

    activity_df.to_csv(data_file, index=True)
    data_file.seek(0)

    return data_file, figure_file


### plotting correlation
def draw_correlation_graph(G: nx.Graph, title="User Interaction Graph"):
    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(G, seed=42)
    weights = [G[u][v]["weight"] for u, v in G.edges()]
    nx.draw(
        G,
        pos,
        with_labels=True,
        width=weights,
        edge_color="skyblue",
        node_color="lightgreen",
        font_size=10,
        node_size=600,
    )
    plt.title(title)
    # plt.tight_layout()
    figure_file = BytesIO()
    plt.savefig(figure_file)
    figure_file.seek(0)
    return figure_file


def normalize_weights(G: nx.Graph, target_min: float = 0.0, target_max: float = 1.0):
    weights = [d["weight"] for _, _, d in G.edges(data=True)]
    if not weights:
        return  # avoid div-by-zero
    min_w = min(weights)
    max_w = max(weights)

    for u, v, d in G.edges(data=True):
        if max_w == min_w:
            d["weight"] = target_max  # or mid value
        else:
            norm = (d["weight"] - min_w) / (max_w - min_w)
            d["weight"] = norm * (target_max - target_min) + target_min


def analyze_interaction_graph(G: nx.Graph) -> pd.DataFrame:
    """
    Compute various node-level metrics on a user interaction graph.

    Args:
        G (nx.Graph): A weighted, undirected NetworkX graph.

    Returns:
        pd.DataFrame: Node metrics indexed by user (usernames or IDs).
    """

    if len(G) == 0:
        return pd.DataFrame()

    centrality = nx.degree_centrality(G)
    weighted_degree = dict(G.degree(weight="weight"))
    betweenness = nx.betweenness_centrality(G, weight="weight", normalized=True)
    closeness = nx.closeness_centrality(
        G, distance=lambda u, v, d: 1 / d["weight"] if d["weight"] > 0 else float("inf")
    )
    pagerank = nx.pagerank(G, weight="weight")
    clustering = nx.clustering(G, weight="weight")

    # Eigenvector may fail if the graph is too sparse or not connected
    try:
        eigenvector = nx.eigenvector_centrality(G, weight="weight", max_iter=500)
    except nx.PowerIterationFailedConvergence:
        eigenvector = {n: 0.0 for n in G.nodes}

    df = pd.DataFrame(
        {
            "Weighted Degree": pd.Series(weighted_degree),
            "Degree Centrality": pd.Series(centrality),
            "Betweenness": pd.Series(betweenness),
            "Closeness": pd.Series(closeness),
            "PageRank": pd.Series(pagerank),
            "Eigenvector": pd.Series(eigenvector),
            "Clustering Coefficient": pd.Series(clustering),
        }
    )
    all_users = list(G.nodes)
    df = df.reindex(all_users)
    df.index.name = "User"

    # Normalize columns (optional)
    return df.sort_values("Weighted Degree", ascending=False)


def get_top_influencers(metrics_df: pd.DataFrame, top_n: int = 5, metric: str = "PageRank") -> pd.DataFrame:
    """
    Returns the top N most influential users by a given metric.

    Args:
        metrics_df (pd.DataFrame): Output from analyze_interaction_graph.
        top_n (int): Number of users to return.
        metric (str): Column to sort by (e.g., 'PageRank', 'Degree Centrality').

    Returns:
        pd.DataFrame: Top N users and their scores.
    """
    if metric not in metrics_df.columns:
        raise ValueError(f"Metric '{metric}' not found in dataframe.")
    return metrics_df.sort_values(metric, ascending=False).head(top_n)


def build_interaction_graph(
    guild: discord.Guild,
    message_data: List[Dict],
    voice_data: List[Dict],
    weights: Dict[str, float] = {"reply": 3.0, "text_overlap": 1.5, "voice": 1.5},
    text_overlap_window: timedelta = timedelta(minutes=5),
    min_edge_weight: float = 5.0,
    user_lookup: Optional[Dict[int, str]] = None,
) -> Tuple[BytesIO, BytesIO, BytesIO, BytesIO]:
    """
    Builds an interaction graph from message and voice data.

    Returns:
        - networkx.Graph: graph object
        - pd.DataFrame: edge list for Gephi (user1, user2, weight)
    """

    def resolve_name(uid):
        return user_lookup.get(uid, str(uid)) if user_lookup else str(uid)

    G = nx.Graph()
    edge_weights = defaultdict(float)

    # Preprocess message data
    msg_df = pd.DataFrame(message_data)
    # msg_df["datetime"] = pd.to_datetime(msg_df["datetime"])
    # msg_df.sort_values("datetime", inplace=True)

    # === REPLIES ===
    reply_map = {m["message_id"]: m["author_id"] for m in message_data if m.get("message_id")}
    for msg in message_data:
        if msg.get("reference_id") and msg["reference_id"] in reply_map:
            source = msg["author_id"]
            target = reply_map[msg["reference_id"]]
            if source != target:
                edge_weights[frozenset((source, target))] += weights["reply"]

    # === TEXT ACTIVITY OVERLAP ===
    for channel_id, group in msg_df.groupby("channel_id"):
        group = group.sort_values("datetime")
        for i, msg1 in group.iterrows():
            window_start = msg1["datetime"]
            window_end = window_start + text_overlap_window
            window_users = group[(group["datetime"] > window_start) & (group["datetime"] <= window_end)][
                "author_id"
            ].unique()

            for other_id in window_users:
                if msg1["author_id"] != other_id:
                    edge_weights[frozenset((msg1["author_id"], other_id))] += weights["text_overlap"]

    # === VOICE ACTIVITY ===
    voice_df = pd.DataFrame(voice_data)
    # voice_df["datetime"] = pd.to_datetime(voice_df["datetime"])
    # voice_df = voice_df.sort_values("datetime")

    # Track channel state: {channel_id: {user_id: join_time}}
    channel_state = defaultdict(dict)

    for _, row in voice_df.iterrows():
        user = row["author_id"]
        action = row["action_type"]
        chan = row["channel_id"]
        moved_to = row.get("moved_to_id")

        if action == "join":
            channel_state[chan][user] = row["datetime"]

        elif action == "leave":
            join_time = channel_state[chan].pop(user, None)
            if join_time:
                for other_user, other_join in channel_state[chan].items():
                    overlap = (row["datetime"] - max(join_time, other_join)).total_seconds()
                    if overlap > 0:
                        edge_weights[frozenset((user, other_user))] += weights["voice"]

        elif action == "move":
            # treat as leave + join
            join_time = channel_state[chan].pop(user, None)
            if join_time:
                for other_user, other_join in channel_state[chan].items():
                    overlap = (row["datetime"] - max(join_time, other_join)).total_seconds()
                    if overlap > 0:
                        edge_weights[frozenset((user, other_user))] += weights["voice"]
            # join new channel
            channel_state[moved_to][user] = row["datetime"]

    # === BUILD GRAPH ===
    for pair, weight in edge_weights.items():
        if weight >= min_edge_weight:
            u, v = tuple(pair)
            G.add_edge(resolve_name(u), resolve_name(v), weight=weight)

    normalize_weights(G, target_min=1.0, target_max=10.0)

    # === CREATE EDGE LIST FOR GEPHI ===
    edge_list = pd.DataFrame(
        [{"user1": resolve_name(u), "user2": resolve_name(v), "weight": d["weight"]} for u, v, d in G.edges(data=True)]
    )

    data_file = BytesIO()
    analysis_file = BytesIO()
    edge_list.to_csv(data_file, index=False)
    data_file.seek(0)

    figure_file = draw_correlation_graph(G, title=f"{guild.name} User Interaction Graph")

    # extra analysis
    # graph metics
    analysis = analyze_interaction_graph(G)
    analysis.to_csv(analysis_file, index=True)
    analysis_file.seek(0)

    # Overall network summary
    summary_file = BytesIO()
    avg_path_length = nx.average_shortest_path_length(G)
    density = nx.density(G)
    num_components = nx.number_connected_components(G)
    top_5_influencers = get_top_influencers(analysis)

    metrics = pd.DataFrame(
        data={
            "metric": [
                "Average Path length",
                "Density",
                "Number of Components",
                "Top 5 Influencers",
                "Weighted Degree",
                "Degree Centrality",
                "Betweenness",
                "Closeness",
                "PageRank",
                "Eigenvector Centrality",
                "Clustering Coefficient",
            ],
            "value": [
                avg_path_length,
                density,
                num_components,
                ",".join(list(top_5_influencers.index)),
                "see per user analysis file",
                "see per user analysis file",
                "see per user analysis file",
                "see per user analysis file",
                "see per user analysis file",
                "see per user analysis file",
                "see per user analysis file",
            ],
            "description": [
                "On average, how many 'hops' it takes for one user to reach another in the community. A lower number means people are more closely connected.",
                "How many connections exist compared to how many could exist. A higher value means a tightly-knit server where most people interact.",
                "The number of separate groups of users that are not connected at all. If it's more than 1, there are isolated cliques or inactive members.",
                "The most central or impactful users in the network based on a mix of activity and connections. These users tend to influence or connect with many others.",
                "How much interaction a user has overall, counting both how many people they talk to and how often.",
                "How many unique people a user interacts with directly — not how deeply, just how many.",
                "How often a user acts as a bridge between others. A high score means they're the “go-between” for separate groups.",
                "How quickly a user can reach everyone else in the network. A higher value means they're closer to others overall.",
                "A measure of influence based on both activity and who they're connected to — like Google's ranking of important web pages.",
                "A more advanced version of PageRank. It values users who are connected to other well-connected users.",
                "How likely it is that a user's contacts also know each other — a measure of how “cliquey” their neighborhood is.",
            ],
        }
    )

    metrics.to_csv(summary_file, index=False)
    summary_file.seek(0)

    return data_file, analysis_file, summary_file, figure_file
