from .personalroles import PersonalRoles

__red_end_user_data_statement__ = "This will store what a user's custom role is if they have one."

def setup(bot):
    bot.add_cog(PersonalRoles(bot))
