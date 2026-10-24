import argparse

from agentgate.infrastructure.persistence.database import initialize


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly seed local simulated accounts")
    parser.add_argument("--database", required=True)
    arguments = parser.parse_args()
    initialize(arguments.database, seed=True)


if __name__ == "__main__":
    main()
