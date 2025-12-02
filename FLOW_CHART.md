# Application Logic Flow

```mermaid
flowchart TD
    A[User selects filters in UI] --> B{Which feature?}
    B -->|Watcher odds| C[POST /api/odds]
    B -->|Value plays| D[POST /api/value-plays]
    B -->|Best value search| E[POST /api/best-value-plays]
    B -->|Player props| F[POST /api/player-props]

    C --> G[Compute bookmaker regions]
    G --> H[Fetch odds (real or dummy)]
    H --> I[Match requested teams/points per bookmaker]
    I --> J[Pick best price per team]
    J --> K[Respond with prices by book]

    D --> L[Validate books & fetch odds]
    L --> M[Collect matching outcomes and adjust vig]
    M --> N[Compute EV %, hedge, and arb margin]
    N --> O[Filter to future games]
    O --> P[Sort by hedge margin; trim max results]
    P --> Q{Include SGP?}
    Q -->|Yes| R[Build 3-leg parlay suggestion]
    Q -->|No| S[Skip]
    R --> T[Respond with value plays + parlay]
    S --> T

    E --> U[Loop sports & markets]
    U --> V[Repeat value-play collection per combo]
    V --> W[Aggregate + sort by hedge margin]
    W --> X[Trim to max results and respond]

    F --> Y[Fetch or generate prop odds]
    Y --> Z[Filter by team/player if provided]
    Z --> AA[Reuse value-play collection, filter future]
    AA --> AB[Sort by EV and respond]
```

## Notes
- All backend routes use the same Odds API wrapper and can switch to dummy odds generation for offline testing or saving API credits.
- Value calculations adjust target-book odds for vig, compare them to a sharp reference book, and surface arbitrage margins when opposite sides line up.
- Finished responses include user-friendly bookmaker labels and formatted start times for upcoming games.
