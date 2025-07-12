__version__ = "0.0.1"

# USERS STATUSES:
# 0: 000 - user wroten by himself
# 1: 001 - answer to above user
# 2: 010 - old dialog from session
# 3: 011 - answer above user
# 4: 100 - user from parsing
# 5: 101 - user from parsing and mailed
# 6: 110 - user added from search
# 7: 111 - dialog with above user
#    |||
#    ||+------ user wait for mail - 0 or we answered for user - 1
#    |+------- work with existing dialog - 1, event adding - 0
#    +-------- user wrote himself - 0 we add user - 1

# Colors in UI:
# #27284A
# #2639A6
# #132D71
# #CDC8B7
# #EDEBE5

# Green buttons
# #3CB371
# #2E8B57
# #1E6240

# Red buttons
# #E74C3C
# #C0392B
# #8E2A20

# datetime.datetime.now(datetime.UTC).timestamp()