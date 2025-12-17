(function (global) {
    const existingRenderers = global.TableRenderers || {};
    const existingHelpers = (global.TableRenderers && global.TableRenderers.helpers) || {};
    const DEFAULT_HEDGE_STAKE = 10;

    function americanToDecimal(odds) {
        if (odds === null || odds === undefined) return null;
        const numOdds = typeof odds === "string" ? parseInt(odds, 10) : odds;
        if (Number.isNaN(numOdds)) return null;
        if (numOdds > 0) {
            return 1.0 + numOdds / 100.0;
        }
        return 1.0 + 100.0 / Math.abs(numOdds);
    }

    function calculateHedgeStakeAmounts(targetOdds, hedgeOdds, baseStake = DEFAULT_HEDGE_STAKE) {
        const targetDecimal = americanToDecimal(targetOdds);
        const hedgeDecimal = americanToDecimal(hedgeOdds);

        if (!targetDecimal || !hedgeDecimal) {
            return null;
        }

        const targetIsShorter = targetDecimal <= hedgeDecimal;
        const shorterDecimal = targetIsShorter ? targetDecimal : hedgeDecimal;
        const longerDecimal = targetIsShorter ? hedgeDecimal : targetDecimal;
        const shorterStake = baseStake;
        const targetPayout = shorterStake * shorterDecimal;
        const longerStake = targetPayout / longerDecimal;

        return {
            targetStake: targetIsShorter ? shorterStake : longerStake,
            hedgeStake: targetIsShorter ? longerStake : shorterStake,
        };
    }

    function formatStakeAmount(amount) {
        if (amount === null || amount === undefined || Number.isNaN(amount)) {
            return null;
        }
        return `$${Number(amount).toFixed(2)}`;
    }

    function formatOdds(odds) {
        if (odds === null || odds === undefined) {
            return "";
        }
        const numOdds = typeof odds === "string" ? parseInt(odds, 10) : odds;
        if (Number.isNaN(numOdds)) {
            return String(odds);
        }
        return numOdds > 0 ? `+${numOdds}` : String(numOdds);
    }

    function getOddsHighlightClass(odds) {
        if (odds === null || odds === undefined) return "odds-hedge-neutral";

        const numericOdds = typeof odds === "string" ? parseInt(odds, 10) : Number(odds);
        if (Number.isNaN(numericOdds)) return "odds-hedge-neutral";

        if (numericOdds <= -200) return "odds-hedge-dark-red";
        if (numericOdds < -115) return "odds-hedge-light-red";
        if (numericOdds >= 200) return "odds-hedge-dark-green";
        if (numericOdds > 115) return "odds-hedge-light-green";

        return "odds-hedge-neutral";
    }

    function formatStartTime(isoString) {
        if (!isoString) return "TBD";
        const date = new Date(isoString);
        if (isNaN(date.getTime())) {
            return isoString;
        }
        const options = {
            weekday: "short",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
        };
        return date.toLocaleString("en-US", options) + " ET";
    }

    function getOddsColorClass(odds) {
        const numOdds = typeof odds === "string" ? parseInt(odds, 10) : odds;
        if (numOdds === null || numOdds === undefined || Number.isNaN(numOdds)) {
            return "";
        }

        const absOdds = Math.abs(numOdds);

        if (absOdds <= 115) return "odds-neutral";

        if (numOdds > 0) {
            if (numOdds >= 350) return "odds-plus-strong";
            if (numOdds >= 200) return "odds-plus";
            if (numOdds >= 120) return "odds-plus-light";
            return "odds-neutral";
        }

        if (numOdds <= -350) return "odds-favorite-strong";
        if (numOdds <= -200) return "odds-favorite";
        if (numOdds <= -120) return "odds-favorite-light";
        return "odds-neutral";
    }

    function formatOddsWithColor(odds) {
        const formatted = formatOdds(odds);
        const className = getOddsColorClass(odds);
        if (!className) return formatted;
        return `<span class="odds-chip ${className}">${formatted}</span>`;
    }

    function defaultParseTeamFromOutcome(outcomeName) {
        if (!outcomeName) return null;
        const parts = outcomeName.split(" @ ");
        return parts[0].trim();
    }

    function defaultParseTeamsFromMatchup(matchup) {
        if (!matchup) return { away: null, home: null };

        const parts = matchup.split(" @ ");
        if (parts.length === 2) {
            return { away: parts[0].trim(), home: parts[1].trim() };
        }
        return { away: matchup, home: null };
    }

    function renderPropRows(tbody, plays, options = {}) {
        const {
            targetBookLabel = "Target",
            compareBookLabel = "Compare",
            sportLabels = {},
            marketLabelGetter = (key) => key,
            startTimeFormatter = formatStartTime,
            oddsFormatter = formatOddsWithColor,
            hedgeOddsFormatter = formatOddsWithColor,
            emptyMessage = "No player prop value plays found.",
        } = options;

        tbody.innerHTML = "";

        const rows = Array.isArray(plays) ? [...plays] : [];
        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="small-text">${emptyMessage}</td></tr>`;
            return;
        }

        rows.forEach(play => {
            const tr = document.createElement("tr");

            const selectionCell = document.createElement("td");
            const marketLabel = typeof marketLabelGetter === "function" ? marketLabelGetter(play.market) : play.market;
            const lineText = play.point !== null && play.point !== undefined ? `${play.point > 0 ? "+" : ""}${play.point}` : "";
            const sportLabel = sportLabels[play.sport_key] || play.sport_label || "";
            const matchupText = play.matchup ? `<div class="small-text">${play.matchup}</div>` : "";
            const sportText = sportLabel ? `<div class="small-text">${sportLabel}</div>` : "";
            const marketText = marketLabel ? `<div class="small-text">${marketLabel} ${lineText}</div>` : "";

            selectionCell.innerHTML = `<strong>${play.outcome_name || ""}</strong>${marketText}${sportText}${matchupText}`;
            tr.appendChild(selectionCell);

            const recommendedCell = document.createElement("td");
            const recommendedOdds = oddsFormatter(play.book_price);
            const targetLabel = play.targetLabel || targetBookLabel;
            const targetStakeLine = play.targetStakeText ? `<div class="small-text hedge-stake">Stake: ${play.targetStakeText}</div>` : "";
            recommendedCell.innerHTML = `<strong>${targetLabel}</strong><br>${recommendedOdds}${targetStakeLine}`;
            tr.appendChild(recommendedCell);

            const hedgeCell = document.createElement("td");
            if (play.novig_reverse_name && play.novig_reverse_price !== null && play.novig_reverse_price !== undefined) {
                const hedgeOdds = hedgeOddsFormatter(play.novig_reverse_price);
                const compareLabel = play.compareLabel || compareBookLabel;
                const hedgeStakeLine = play.hedgeStakeText ? `<div class="small-text hedge-stake">Hedge Stake: ${play.hedgeStakeText}</div>` : "";
                hedgeCell.innerHTML = `<strong>${play.novig_reverse_name}</strong><br>${hedgeOdds}<br><span class="small-text">@ ${compareLabel}</span>${hedgeStakeLine}`;
            } else {
                hedgeCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(hedgeCell);

            const edgeCell = document.createElement("td");
            if (play.arb_margin_percent !== null && play.arb_margin_percent !== undefined) {
                const arbRounded = Math.round(play.arb_margin_percent * 100) / 100;
                const arbClass = arbRounded >= 0 ? "badge badge-positive" : "badge badge-negative";
                edgeCell.innerHTML = `<span class="${arbClass}">${arbRounded}%</span>`;
            } else {
                edgeCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(edgeCell);

            const startCell = document.createElement("td");
            const startText = startTimeFormatter(play.start_time);
            const startMatchupText = play.matchup ? `<div class="small-text">${play.matchup}</div>` : "";
            startCell.innerHTML = `${startText}${startMatchupText}`;
            tr.appendChild(startCell);

            tbody.appendChild(tr);
        });
    }

    function renderArbRows(tbody, plays, options = {}) {
        const {
            includeSportColumn = true,
            sportLabels = {},
            marketLabels = {},
            targetBookLabel = "Target",
            compareBookLabel = "Compare",
            emptyMessage = "No arbitrage opportunities found.",
            hedgeOnly = false,
            showLogos = false,
            sortPlays,
            getTeamLogoUrl,
            parseTeamFromOutcome = defaultParseTeamFromOutcome,
            parseTeamsFromMatchup = defaultParseTeamsFromMatchup,
            oddsFormatter = formatOdds,
            oddsHighlightClassGetter = getOddsHighlightClass,
            startTimeFormatter = formatStartTime,
            hedgeStakeCalculator = calculateHedgeStakeAmounts,
            stakeFormatter = formatStakeAmount,
        } = options;

        tbody.innerHTML = "";
        let rows = Array.isArray(plays) ? [...plays] : [];

        if (hedgeOnly) {
            rows = rows.filter(p =>
                p.novig_reverse_name !== null &&
                p.novig_reverse_name !== undefined &&
                p.novig_reverse_price !== null &&
                p.novig_reverse_price !== undefined,
            );
        }

        if (typeof sortPlays === "function") {
            rows = sortPlays(rows);
        }

        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="small-text">${emptyMessage}</td></tr>`;
            return;
        }

        rows.forEach(play => {
            const tr = document.createElement("tr");
            const marketLabel = marketLabels[play.market] || play.market || "";
            const sportLabel = sportLabels[play.sport_key] || play.sport_key || "";
            const hedgeStakeAmounts = hedgeStakeCalculator(play.book_price, play.novig_reverse_price);
            const targetStakeText = hedgeStakeAmounts ? stakeFormatter(hedgeStakeAmounts.targetStake) : null;
            const hedgeStakeText = hedgeStakeAmounts ? stakeFormatter(hedgeStakeAmounts.hedgeStake) : null;

            const selectionCell = document.createElement("td");
            const teamName = parseTeamFromOutcome(play.outcome_name);
            const lineText = play.point !== null && play.point !== undefined ? `${play.point > 0 ? "+" : ""}${play.point}` : "";
            const matchupText = play.matchup ? `<div class="small-text">${play.matchup}</div>` : "";

            if (includeSportColumn) {
                selectionCell.textContent = sportLabel || "-";
            } else {
                const sportLine = sportLabel ? `<div class="small-text">${sportLabel}</div>` : "";
                selectionCell.innerHTML = `<strong>${teamName || play.outcome_name || ""}</strong>${sportLine}<div class="small-text">${marketLabel || ""} ${lineText}</div>${matchupText}`;
            }
            tr.appendChild(selectionCell);

            const recommendedCell = document.createElement("td");
            recommendedCell.className = "bet-cell";
            const betOddsClass = oddsHighlightClassGetter(play.book_price);
            const formattedOdds = oddsFormatter(play.book_price);
            const targetRow = document.createElement("div");
            targetRow.className = "bet-row";

            if (showLogos && typeof getTeamLogoUrl === "function") {
                let logoTeamName = teamName;
                if (play.market === "totals" && play.matchup) {
                    const teams = parseTeamsFromMatchup(play.matchup);
                    logoTeamName = teams.away || teams.home || null;
                }
                if (logoTeamName) {
                    const logo = document.createElement("img");
                    logo.className = "team-logo";
                    logo.src = getTeamLogoUrl(logoTeamName, play.sport_key || null);
                    logo.alt = logoTeamName;
                    logo.onerror = function () { this.style.display = "none"; };
                    targetRow.appendChild(logo);
                }
            }

            const betText = document.createElement("div");
            betText.className = "bet-text";
            let betDescription = "";
            if (play.market === "totals") {
                betDescription = `${play.outcome_name || "Total"}`;
                if (play.matchup) {
                    betDescription += ` - ${play.matchup}`;
                }
            } else {
                betDescription = `${teamName || ""} ${marketLabel === "Moneyline" ? "ML" : marketLabel === "Spreads" ? "Spread" : marketLabel}`.trim();
                if (lineText) {
                    betDescription += ` ${lineText}`;
                }
            }
            betText.innerHTML = `<div><strong>${betDescription} <span class="odds-highlight ${betOddsClass}">${formattedOdds}</span></strong></div><div class="small-text">@ ${targetBookLabel}</div>`;
            if (targetStakeText) {
                const stakeNote = document.createElement("div");
                stakeNote.className = "small-text hedge-stake";
                stakeNote.textContent = `Hedge Stake: ${targetStakeText}`;
                betText.appendChild(stakeNote);
            }
            targetRow.appendChild(betText);
            recommendedCell.appendChild(targetRow);
            tr.appendChild(recommendedCell);

            const hedgeCell = document.createElement("td");
            hedgeCell.className = "bet-cell";
            if (play.novig_reverse_price !== null && play.novig_reverse_price !== undefined && play.novig_reverse_name) {
                const hedgeRow = document.createElement("div");
                hedgeRow.className = "bet-row";
                const formattedHedgeOdds = oddsFormatter(play.novig_reverse_price);
                const hedgeOddsClass = oddsHighlightClassGetter(play.novig_reverse_price);
                let oppositeTeamName = parseTeamFromOutcome(play.novig_reverse_name);
                const hedgeMarketLabel = marketLabels[play.market] || play.market;

                let hedgeDescription = "";
                if (play.market === "totals") {
                    hedgeDescription = play.novig_reverse_name;
                } else if (play.market === "spreads") {
                    hedgeDescription = `${oppositeTeamName || ""} ${hedgeMarketLabel === "Spreads" ? "Spread" : hedgeMarketLabel}`.trim();
                    if (lineText) {
                        const oppositePoint = -(play.point || 0);
                        hedgeDescription += ` ${oppositePoint > 0 ? "+" : ""}${oppositePoint}`;
                    }
                } else {
                    hedgeDescription = `${oppositeTeamName || ""} ML`.trim();
                }

                const hedgeText = document.createElement("div");
                hedgeText.className = "bet-text";
                hedgeText.innerHTML = `<div><strong>${hedgeDescription} <span class="odds-highlight ${hedgeOddsClass}">${formattedHedgeOdds}</span></strong></div><div class="small-text">@ ${compareBookLabel}</div>`;
                if (hedgeStakeText) {
                    const stakeNote = document.createElement("div");
                    stakeNote.className = "small-text hedge-stake";
                    stakeNote.textContent = `Hedge Stake: ${hedgeStakeText}`;
                    hedgeText.appendChild(stakeNote);
                }

                hedgeRow.appendChild(hedgeText);
                hedgeCell.appendChild(hedgeRow);
            } else {
                hedgeCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(hedgeCell);

            const hedgeEvCell = document.createElement("td");
            if (play.arb_margin_percent !== null && play.arb_margin_percent !== undefined) {
                const hedgeRounded = Math.round(play.arb_margin_percent * 100) / 100;
                const hedgeClass = hedgeRounded >= 0 ? "badge badge-positive" : "badge badge-negative";
                hedgeEvCell.innerHTML = `<span class="${hedgeClass}">${hedgeRounded}%</span>`;
            } else {
                hedgeEvCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(hedgeEvCell);

            const startCell = document.createElement("td");
            startCell.textContent = startTimeFormatter(play.start_time);
            tr.appendChild(startCell);

            tbody.appendChild(tr);
        });
    }

    function renderPropRows(tbody, plays, options = {}) {
        const {
            targetBookLabel = "Target",
            compareBookLabel = "Compare",
            sportLabels = {},
            marketLabelGetter = (key) => key,
            startTimeFormatter = formatStartTime,
            emptyMessage = "No player prop value plays found.",
            oddsFormatter = formatOddsWithColor,
            hedgeOddsFormatter = formatOddsWithColor,
        } = options;

        tbody.innerHTML = "";
        const rows = Array.isArray(plays) ? [...plays] : [];

        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="small-text">${emptyMessage}</td></tr>`;
            return;
        }

        rows.forEach(play => {
            const tr = document.createElement("tr");
            const sportLabel = play.sport_key ? (sportLabels[play.sport_key] || play.sport_key) : "";
            const rowTargetLabel = play.targetLabel || targetBookLabel;
            const rowCompareLabel = play.compareLabel || compareBookLabel;

            const playerCell = document.createElement("td");
            const marketLabel = marketLabelGetter(play.market || "") || "";
            const lineText = play.point !== null && play.point !== undefined ? ` @ ${play.point}` : "";
            const sportLine = sportLabel ? `<div class="small-text">${sportLabel}</div>` : "";
            const matchupLine = play.matchup ? `<div class="small-text">${play.matchup}</div>` : "";
            playerCell.innerHTML = `<strong>${play.outcome_name || ""}</strong>${sportLine}<span class="small-text">${marketLabel}${lineText}</span>${matchupLine}`;
            tr.appendChild(playerCell);

            const targetCell = document.createElement("td");
            const formattedTargetOdds = oddsFormatter(play.book_price);
            const targetStakeText = play.targetStakeText || "";
            const matchupText = play.matchup ? `<span class="small-text">${play.matchup}</span><br>` : "";
            const stakeLine = targetStakeText ? `<div class="small-text hedge-stake">Hedge Stake: ${targetStakeText}</div>` : "";
            targetCell.innerHTML = `${matchupText}<strong>${formattedTargetOdds}</strong><br><span class="small-text">@ ${rowTargetLabel}</span>${stakeLine}`;
            tr.appendChild(targetCell);

            const hedgeCell = document.createElement("td");
            if (play.novig_reverse_name && play.novig_reverse_price !== null && play.novig_reverse_price !== undefined) {
                const formattedHedgeOdds = hedgeOddsFormatter(play.novig_reverse_price);
                const hedgeStakeLine = play.hedgeStakeText ? `<div class="small-text hedge-stake">Hedge Stake: ${play.hedgeStakeText}</div>` : "";
                hedgeCell.innerHTML = `<strong>${play.novig_reverse_name}</strong><br>${formattedHedgeOdds}<br><span class="small-text">@ ${rowCompareLabel}</span>${hedgeStakeLine}`;
            } else {
                hedgeCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(hedgeCell);

            const arbCell = document.createElement("td");
            if (play.arb_margin_percent !== null && play.arb_margin_percent !== undefined) {
                const arbRounded = Math.round(play.arb_margin_percent * 100) / 100;
                const arbClass = arbRounded >= 0 ? "badge badge-positive" : "badge badge-negative";
                arbCell.innerHTML = `<span class="${arbClass}">${arbRounded}%</span>`;
            } else {
                arbCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(arbCell);

            const startCell = document.createElement("td");
            startCell.textContent = startTimeFormatter(play.start_time);
            tr.appendChild(startCell);

            tbody.appendChild(tr);
        });
    }

    function renderPropComparisonRows(tbody, plays, options = {}) {
        const {
            bookOrder = ["novig", "draftkings", "fanduel", "fliff"],
            oddsFormatter = formatOddsWithColor,
            startTimeFormatter = formatStartTime,
            emptyMessage = "No player prop prices available for comparison.",
        } = options;

        tbody.innerHTML = "";

        const rows = Array.isArray(plays) ? [...plays] : [];
        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="${bookOrder.length + 3}" class="small-text">${emptyMessage}</td></tr>`;
            return;
        }

        rows.forEach((play) => {
            const tr = document.createElement("tr");
            const lineText = play.point !== null && play.point !== undefined ? `${play.point > 0 ? "+" : ""}${play.point}` : "";

            const selectionCell = document.createElement("td");
            const marketLabel = play.market ? `<div class="small-text">${play.market} ${lineText}</div>` : "";
            const matchup = play.matchup ? `<div class="small-text">${play.matchup}</div>` : "";
            selectionCell.innerHTML = `<strong>${play.outcome_name || ""}</strong>${marketLabel}${matchup}`;
            tr.appendChild(selectionCell);

            const arbCell = document.createElement("td");
            if (play.arb_margin_percent !== null && play.arb_margin_percent !== undefined) {
                const arbRounded = Math.round(play.arb_margin_percent * 100) / 100;
                const arbClass = arbRounded >= 0 ? "badge badge-positive" : "badge badge-negative";
                arbCell.innerHTML = `<span class="${arbClass}">${arbRounded}%</span>`;
            } else {
                arbCell.innerHTML = '<span class="small-text">-</span>';
            }
            tr.appendChild(arbCell);

            bookOrder.forEach((bookKey) => {
                const cell = document.createElement("td");
                const bookPrices = play.book_prices || {};
                const opposingPrices = play.opposing_prices || {};
                const mainPrice = bookPrices[bookKey];
                const hedgePrice = opposingPrices[bookKey];

                const mainText = mainPrice !== null && mainPrice !== undefined
                    ? oddsFormatter(mainPrice)
                    : '<span class="small-text">—</span>';
                const hedgeText = hedgePrice !== null && hedgePrice !== undefined
                    ? `<div class="small-text">Opp: ${oddsFormatter(hedgePrice)}</div>`
                    : "";

                cell.innerHTML = `${mainText}${hedgeText}`;
                tr.appendChild(cell);
            });

            const startCell = document.createElement("td");
            startCell.textContent = startTimeFormatter(play.start_time);
            tr.appendChild(startCell);

            tbody.appendChild(tr);
        });
    }

    global.TableRenderers = {
        ...existingRenderers,
        renderArbRows,
        renderPropRows,
        renderPropComparisonRows,
        helpers: {
            ...existingHelpers,
            formatOdds,
            formatOddsWithColor,
            formatStartTime,
            calculateHedgeStakeAmounts,
            formatStakeAmount,
            getOddsHighlightClass,
        }
    };
})(window);
