"""Owned rehearsal shutdown ordering, with caller-owned resource operations."""


def shutdown_owned(containers, stop, release, on_error):
    """Release only after every stop; return stop confirmation, never cleanup certification."""
    stopped = True
    for container in reversed(tuple(containers)):
        try:
            stop(container)
        except Exception as error:
            stopped = False
            on_error(error)
    if not stopped:
        return False
    try:
        release()
    except Exception as error:
        on_error(error)
    return True
