# Player Props Future Changes Research

This note tracks forward-looking ideas for improving the player props experience beyond the current NBA and NFL implementations.

## Potential Enhancements

- **Add more player performance combos**: Explore supporting combination lines such as points + assists (NBA) or rushing + receiving yards (NFL) when those markets are consistently available across books. This will require confirming market keys from The Odds API and expanding dummy data ranges.
- **Allow book-specific market fallbacks**: Detect when a selected market is missing from the target or comparison book and automatically substitute the closest available market (e.g., receptions vs. receiving yards), with clear UI messaging about the substitution.
- **Historical trend overlays**: Incorporate recent player performance averages and opponent defensive ranks alongside each prop to help users judge the quality of a value edge beyond odds comparisons.
- **Alerting and watchlists**: Let users save favorite players/markets and notify them when a new edge appears, reusing the existing watcher infrastructure to poll selected props.
- **Cross-sport templates**: Add presets for common search stacks (e.g., "All Passing Props" or "Core NBA Shooting Props") so users can quickly run multi-market queries without manually selecting each checkbox.
