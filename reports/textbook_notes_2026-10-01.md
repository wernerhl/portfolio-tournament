# Textbook notes — 1 October 2026

For folding into the textbook (math track) and the lay essay (plain-language track). The agent does not edit either; they live outside the repository. Order "Rates and Bond Monitor Corrections" (1 October 2026), item R8. Numbers are the 29–30 September 2026 readings served on 1 October.

---

## 1. A 252-session z and a ten-year percentile answer different questions

### Math track

For a daily series x, the regime model's status uses a rolling standardization over the trailing L = 252 sessions:

z_t = (x_t − m_t) / s_t,  m_t = mean(x_{t−251..t}),  s_t = sd(x_{t−251..t}),

oriented so that higher means riskier (z is negated for channels where lower is riskier), mapped to a risk score φ_t = Φ(z_t), and bucketed: φ < 0.40 below the norm, 0.40–0.60 near it, 0.60–0.80 above it, ≥ 0.80 "Extreme (1y)". The ten-year percentile is a different statistic:

p_t = 100 · #{s ∈ (t − 10y, t] : x_s < x_t} / #{s ∈ (t − 10y, t]}.

z answers "how unusual is today against the last year?"; p answers "where does today sit in the long record?". They diverge whenever the last year was itself unusual. On 30 September 2026, HY OAS was 308bp: z = +1.27 on 252 sessions (85th percentile of the trailing year), z = −0.05 on 756 sessions, and the 47th percentile of ten years. The dollar index (DXY 101.4) was in the top decile of its year and at the 70th percentile of ten years. A status that is "extreme" against one year can be ordinary against ten. Both are shown so neither is mistaken for the other; the model's status uses only the first, and that is unchanged.

### Plain-language track

Each card compares today's reading with the past year. That tells you whether something has moved a lot recently. It does not tell you whether the level is high in the long run. Credit spreads in late September were wider than almost all of the past year, which is why the card is coloured. Against the past ten years they were in the middle of the range. So the card now shows both numbers: how far today sits from its past-year norm, and where it falls in ten years of history.

---

## 2. The curve-implied yield

### Math track

The Treasury constant-maturity (CMT) yields y(τ) at τ ∈ {0.25, 1, 2, 5, 7, 10, 20, 30} years are par yields on a semiannual basis. A sleeve with weighted-average maturity T (from the issuer's fund page) is assigned the linearly interpolated yield

y(T) = y(τ_i) + [y(τ_{i+1}) − y(τ_i)] · (T − τ_i) / (τ_{i+1} − τ_i),  τ_i ≤ T ≤ τ_{i+1}.

Credit sleeves add a spread: the investment-grade option-adjusted spread of the maturity bucket containing T (ICE BofA 1–3, 3–5, 5–7, 7–10, 10–15, 15+ years), or the high-yield OAS. TIPS sleeves use the real curve (DFII) and are excluded from nominal comparisons. On 29 September: IEF (T = 8.42) sits between the 7-year (5.16 percent) and the 10-year (5.26 percent), so y = 5.16 + 0.10 × 1.42/3 = 5.207 percent. It is called curve-implied because a fund's own portfolio yield differs by coupon, convexity and composition.

The figure it replaces, the trailing distribution yield (income paid over the past year divided by price), lags rate moves: IEF's was 3.97 percent on the same day, more than a point below the curve.

### Plain-language track

To ask what a bond fund earns at today's rates, read the Treasury yield curve at the fund's average maturity. A fund holding bonds that mature in about eight years earns roughly the eight-year Treasury rate, plus a credit spread if the bonds are corporate. The older figure on the page, the income the fund paid out over the past year, reflects the rates of a year ago. With rates up sharply since then, it understated what a fund buys today.

---

## 3. The breakeven rise: when does extra yield stop paying?

### Math track

A bond with modified duration D changes price by ΔP/P ≈ −D·Δy for a parallel yield change Δy. Over one year, holding the bond returns approximately y − D·Δy (ignoring roll-down and convexity), while bills return y_cash. Extension pays off when y − D·Δy > y_cash, so the parallel rise that erases the pickup is

Δy* = (y − y_cash) / D.

IEF on 29 September: pickup 95.7bp over DGS3MO (4.25 percent), D = 7.3, Δy* = 13.1bp. TLT: 136.0bp, D = 16.5, Δy* = 8.2bp. For scale, the standard deviation of daily changes in the 10-year yield over the last 126 sessions was 4.43bp, so IEF's cushion is about three typical daily moves and TLT's about two. A typical move over a whole year is larger, about 4.43 × √252 ≈ 70bp under independent daily changes, which is why the cushion is thin.

Omitted terms, named: **roll-down** (on an upward-sloping curve a bond's yield falls as it ages toward shorter maturities, adding return), and **convexity** (+½·C·Δy², which softens losses and enlarges gains). Both make the true breakeven somewhat larger than Δy*.

### Plain-language track

Longer bonds pay more than bills today, about one point more for a seven-to-ten-year fund. But if long rates rise, their prices fall. The breakeven rise is how far rates would have to climb over a year to wipe out that extra income. For the seven-to-ten-year fund it is about 13 hundredths of a point: roughly three ordinary days' worth of movement in the 10-year yield. That says the extra yield is a thin cushion. It does not say rates will rise.

---

## 4. The par-bond duration

### Math track

A par bond pays a semiannual coupon c = y/2 per unit face, so its price is 1. Its modified duration has the closed form

D_par(y, T) = [1 − (1 + y/2)^(−2T)] / y.

(Macaulay duration of a par bond is (1 + y/2)/y · [1 − (1 + y/2)^(−2T)]; dividing by (1 + y/2) gives modified duration.) It depends only on the yield and the maturity, so it is point-in-time by construction. At y = 5.2 percent and T = 8.42, D_par = 6.75; the issuer's effective duration for IEF on 29 September was 6.84. Registration v2 of the bond carry test (`reports/bonds_retirement_registration_v2_2026-10-01.md`) uses b = (y_m − y_3m)/D_par: carry per unit of rate risk, measured on the curve rather than on trailing income.

### Plain-language track

Duration measures how much a bond's price moves when rates move. For a bond priced at face value there is an exact formula using only its yield and its time to maturity. That lets a test measure each fund's rate risk as it was on any past date, with nothing looked up afterwards.

---

## 5. What MOVE measures

### Math track

The ICE BofA MOVE index is a yield-curve-weighted average of the normalized implied volatility of one-month options on 2-, 5-, 10- and 30-year Treasuries (weights 20/20/40/20), quoted in basis points of annualized yield volatility. MOVE = 110 implies a typical annualized move of about 110bp in yields, about 110/√252 ≈ 6.9bp a day. On 30 September 2026 MOVE was 110.45, at the 98.8th percentile of the past 252 sessions and the 81st of ten years, against 70.25 sixty sessions earlier. The realized daily standard deviation of the 10-year over the last 126 sessions, 4.43bp (≈70bp annualized), is well below the implied figure: options were pricing more movement than the recent past delivered. ICE publishes no free official close; the dashboard records yfinance's `^MOVE` as the provider and marks a session without a value as unavailable.

### Plain-language track

MOVE is the bond market's counterpart to the VIX. It measures how much movement in Treasury yields option buyers are paying to protect against. At the end of September it was higher than on almost any day of the past year. It is shown on the dashboard as a diagnostic: it is not part of the regime index, and nothing on the site acts on it until a registered test says it adds information.

---

## 6. Where Treasury auction dates come from

### Math track (provenance)

Auction dates are published, not derived. Three sources, in order of authority: (1) **announced auctions**, from TreasuryDirect's securities service (`TA_WS/securities/upcoming`), typically a few days to a week before each auction, including whether a security is a new issue or a reopening; (2) **the tentative auction schedule**, published quarterly by the Treasury on home.treasury.gov, for dates not yet announced, flagged tentative until replaced by an announcement; (3) **the quarterly refunding statement**, whose date comes from the Treasury's quarterly-refunding page (the next is 4 November 2026, 08:30 ET, as that page states). A date generated from a calendar pattern (for example "the 10-year on the second Wednesday") breaks on holidays and on months whose structure differs. The dashboard's pattern generator, verified only for July 2026, placed the October 3-, 10- and 30-year auctions one week late (13–15 October instead of 6–8 October) and omitted the 2-, 5-, 7- and 20-year and TIPS auctions. The advisor relayed two of those dates without checking the primary source; that error is in the mistakes ledger.

### Plain-language track

The Treasury announces each auction date itself. The dashboard used to guess the dates from a monthly pattern, and in October the guess was a week late. The dates now come straight from the Treasury's own announcements and its published tentative schedule, with the link recorded beside each one.
