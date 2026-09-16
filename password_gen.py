import secrets
import string


def generate_password(length: int) -> str:
    """Generate a strong, cryptographically secure random password."""
    if length < 4:
        raise ValueError("Password length must be at least 4 characters.")

    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*()_+-=[]{}|;:,.<>?"

    # Guarantee at least one character from each character category
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]

    all_characters = lowercase + uppercase + digits + symbols
    password += [secrets.choice(all_characters) for _ in range(length - 4)]

    # Cryptographically secure in-place shuffle
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def main():
    try:
        user_input = input("Enter the desired password length: ")
        length = int(user_input.strip())
        password = generate_password(length)
        print(f"Generated password: {password}")
    except ValueError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
