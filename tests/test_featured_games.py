import main


def test_featured_games_sorted_and_uses_dummy_data():
    payload = main.list_featured_games(use_dummy_data=True)
    games = payload.games

    assert games, "Expected at least one featured game when using dummy data"
    scores = [game.popularity_score for game in games]
    assert scores == sorted(scores, reverse=True)
    assert payload.used_dummy_data is True
