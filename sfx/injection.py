    #### INJECTED BY SFX COG ####
    async def sfx_play(self, ctx: commands.Context, query: str, volume = 100):
        ### From play command, process query and check if can play in this context ###
        query = Query.process_input(query, self.local_folder_current_path)
        import datetime

        if not self._player_check(ctx):
            if self.lavalink_connection_aborted:
                msg = _("Connection to Lavalink has failed")
                desc = EmptyEmbed
                if await self.bot.is_owner(ctx.author):
                    desc = _("Please check your console or logs for details.")
                return await self.send_embed_msg(ctx, title=msg, description=desc)
            try:
                if (
                    not ctx.author.voice.channel.permissions_for(ctx.me).connect
                    or not ctx.author.voice.channel.permissions_for(ctx.me).move_members
                    and self.is_vc_full(ctx.author.voice.channel)
                ):
                    return await self.send_embed_msg(
                        ctx,
                        title=_("Unable To Play Tracks"),
                        description=_("I don't have permission to connect to your channel."),
                    )
                await lavalink.connect(ctx.author.voice.channel)
                player = lavalink.get_player(ctx.guild.id)
                player.store("connect", datetime.datetime.utcnow())
            except AttributeError:
                return await self.send_embed_msg(
                    ctx,
                    title=_("Unable To Play Tracks"),
                    description=_("Connect to a voice channel first."),
                )
            except IndexError:
                return await self.send_embed_msg(
                    ctx,
                    title=_("Unable To Play Tracks"),
                    description=_("Connection to Lavalink has not yet been established."),
                )

        ### PLAYER SETTINGS ###
        player = lavalink.get_player(ctx.guild.id)

        player.store("channel", ctx.channel.id)
        player.store("guild", ctx.guild.id)
        await self._eq_check(ctx, player)

        player.repeat = False
        player.shuffle = False
        player.shuffle_bumped = True
        if player.volume != volume:
            await player.set_volume(volume)

        if len(player.queue) >= 10000:
            return await self.send_embed_msg(
                ctx, title=_("Unable To Play Tracks"), description=_("Queue size limit reached.")
            )

        try:
            await self.sfx_enqueue_tracks(ctx, query)
        except QueryUnauthorized as err:
            return await self.send_embed_msg(
                ctx, title=_("Unable To Play Tracks"), description=err.message
            )

    async def sfx_enqueue_tracks(
        self, ctx: commands.Context, query: Query, enqueue: bool = True
    ) -> Union[discord.Message, List[lavalink.Track], lavalink.Track]:
        player = lavalink.get_player(ctx.guild.id)
        try:
            if self.play_lock[ctx.message.guild.id]:
                return await self.send_embed_msg(
                    ctx,
                    title=_("Unable To Get Tracks"),
                    description=_("Wait until the playlist has finished loading."),
                )
        except KeyError:
            self.update_player_lock(ctx, True)
        guild_data = await self.config.guild(ctx.guild).all()
        first_track_only = False
        single_track = None
        index = None
        playlist_data = None
        playlist_url = None
        seek = 0

        if not await self.is_query_allowed(
            self.config, ctx.guild, f"{query}", query_obj=query
        ):
            raise QueryUnauthorized(
                _("{query} is not an allowed query.").format(query=query.to_string_user())
            )
        if query.single_track:
            first_track_only = True
            index = query.track_index
            if query.start_time:
                seek = query.start_time
        try:
            result, called_api = await self.api_interface.fetch_track(ctx, player, query)
        except TrackEnqueueError:
            self.update_player_lock(ctx, False)
            return await self.send_embed_msg(
                ctx,
                title=_("Unable to Get Track"),
                description=_(
                    "I'm unable get a track from Lavalink at the moment, "
                    "try again in a few minutes."
                ),
            )
        tracks = result.tracks
        playlist_data = result.playlist_info
        if not enqueue:
            return tracks
        if not tracks:
            self.update_player_lock(ctx, False)
            title = _("Nothing found.")
            embed = discord.Embed(title=title)
            if result.exception_message:
                if "Status Code" in result.exception_message:
                    embed.set_footer(text=result.exception_message[:2000])
                else:
                    embed.set_footer(text=result.exception_message[:2000].replace("\n", ""))
            if await self.config.use_external_lavalink() and query.is_local:
                embed.description = _(
                    "Local tracks will not work "
                    "if the `Lavalink.jar` cannot see the track.\n"
                    "This may be due to permissions or because Lavalink.jar is being run "
                    "in a different machine than the local tracks."
                )
            elif query.is_local and query.suffix in _PARTIALLY_SUPPORTED_MUSIC_EXT:
                title = _("Track is not playable.")
                embed = discord.Embed(title=title)
                embed.description = _(
                    "**{suffix}** is not a fully supported format and some "
                    "tracks may not play."
                ).format(suffix=query.suffix)
            return await self.send_embed_msg(ctx, embed=embed)

        queue_dur = await self.queue_duration(ctx)
        queue_total_duration = self.format_time(queue_dur)
        before_queue_length = len(player.queue)


        single_track = None
        # a ytsearch: prefixed item where we only need the first Track returned
        # this is in the case of [p]play <query>, a single Spotify url/code
        # or this is a localtrack item
        try:
            if len(player.queue) >= 10000:
                return await self.send_embed_msg(ctx, title=_("Queue size limit reached."))

            single_track = (
                tracks
                if isinstance(tracks, lavalink.rest_api.Track)
                else tracks[index]
                if index
                else tracks[0]
            )
            if seek and seek > 0:
                single_track.start_timestamp = seek * 1000
            if not await self.is_query_allowed(
                self.config,
                ctx.guild,
                (
                    f"{single_track.title} {single_track.author} {single_track.uri} "
                    f"{str(Query.process_input(single_track, self.local_folder_current_path))}"
                ),
            ):
                if IS_DEBUG:
                    log.debug(f"Query is not allowed in {ctx.guild} ({ctx.guild.id})")
                self.update_player_lock(ctx, False)
                return await self.send_embed_msg(
                    ctx, title=_("This track is not allowed in this server.")
                )
            elif guild_data["maxlength"] > 0:
                if self.is_track_length_allowed(single_track, guild_data["maxlength"]):
                    player.add(ctx.author, single_track)
                    player.maybe_shuffle()
                    self.bot.dispatch(
                        "red_audio_track_enqueue",
                        player.channel.guild,
                        single_track,
                        ctx.author,
                    )
                else:
                    self.update_player_lock(ctx, False)
                    return await self.send_embed_msg(
                        ctx, title=_("Track exceeds maximum length.")
                    )

            else:
                player.add(ctx.author, single_track)
                player.maybe_shuffle()
                self.bot.dispatch(
                    "red_audio_track_enqueue", player.channel.guild, single_track, ctx.author
                )
        except IndexError:
            self.update_player_lock(ctx, False)
            title = _("Nothing found")
            desc = EmptyEmbed
            if await self.bot.is_owner(ctx.author):
                desc = _("Please check your console or logs for details.")
            return await self.send_embed_msg(ctx, title=title, description=desc)

        if not player.current:
            await player.play()
        self.update_player_lock(ctx, False)
        return single_track or message

    ### END INJECTION BY SFX ###
