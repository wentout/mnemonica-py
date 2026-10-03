"""Wrong argument types must be rejected (the stubs are not vacuous)."""

from form_a import User

user = User("ada")
admin = user.Admin(42)  # error: arg-type (str expected)
print(admin)
