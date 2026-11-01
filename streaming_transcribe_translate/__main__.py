import sys


def run() -> None:
    if "--tk" in sys.argv[1:]:
        sys.argv = [arg for arg in sys.argv if arg != "--tk"]
        from .desktop_app import main
    else:
        from .web_server import main
    main()


if __name__ == "__main__":
    run()
