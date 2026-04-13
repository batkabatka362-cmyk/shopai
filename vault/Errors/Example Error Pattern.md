---
title: Example Error Pattern
tags:
  - error
  - example
severity: low
status: resolved
date: 2026-04-13
---
# Example Error Pattern

## Юу болсон

Энэ бол жишээ error note. Бодит алдаа гарах бүрт ийм
форматаар бичнэ.

## Шалтгаан

- `requirements.txt`-д `requests` library дутуу байсан
- CI дээр adapter тестүүд 182 fail болсон
- Локал дээр ажилладаг байсан (requests суусан байсан)

## Нөлөөлөл

- PR #18 дээр CI улаан болсон
- [[Adapter Pattern]]-ийн бүх SMS, email, shipping тестүүд fail

## Шийдэл

`requests>=2.28` нэмж `requirements.txt`-д оруулсан.

## Сургамж

- CI environment нь локал-аас өөр — бүх dependency explicit байх ёстой
- `_REQUESTS_AVAILABLE` guard нь сайн pattern, гэхдээ dep бүртгэх хэрэгтэй

## Холбоотой

- [[Adapter Pattern]] — adapter бүтэц
- [[ShopAI Architecture]] — системийн ерөнхий бүтэц
