# SZ Housing Prices (深圳房价透明)

Make Shenzhen's rental and housing market transparent for normal people.

## What

A simple app that shows rental and purchase reference prices on a map, using government-published data as the anchor. Starting with Shenzhen.

## Why

- China's property market is agency-dominated (贝壳/链家); price transparency is poor, especially for rentals
- Government reference prices exist but are buried in spreadsheets, not accessible to normal users
- People discuss prices on 小红书 but information is fragmented and hidden

## Data

Source: 深圳市住房和建设局 (Shenzhen Housing and Construction Bureau)

- `xiaoqu_geocoded.csv` — 小区 rental reference prices with coordinates
- `chengzhongcun_geocoded.csv` — 城中村 rental reference prices with coordinates
- `shenzhen_rent_reference.csv` — raw rental reference data
- Original government CSVs (Chinese filenames)

## Status

MVP — validating market demand before building the full product.
