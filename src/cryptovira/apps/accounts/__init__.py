"""User identity and authentication. Deliberately thin — see docs/adr/0005-custom-user-model.md
for why Telegram linkage, referrals, credit wallets, and trading preferences all live in *other*
apps' models with a ForeignKey(User), rather than as columns here.
"""
