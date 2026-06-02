# DynoSim

A random project I built after wondering how engine dynos work and whether I could simulate one with Python.

The idea is simple: enter engine specifications such as displacement, compression ratio, fuel type, boost pressure, etc., and the application generates an estimated horsepower and torque curve. It also provides AI-generated tuning suggestions based on the engine setup.

## Features

* Dyno curve generation
* Horsepower and torque estimation
* Support for NA, turbocharged, and supercharged engines
* AI-based tuning recommendations
* FastAPI backend

## Tech Stack

* Python
* FastAPI
* Pydantic
* Anthropic Claude API
* HTML/CSS/JavaScript

## Running the Project

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open:

```
http://127.0.0.1:8000
```

## Note

This is not a physically accurate engine simulator. The dyno curves are generated using simplified calculations and assumptions. The project was mainly built as an experiment to combine simulation logic with AI-generated analysis.

## Why I Built It

Honestly, I was just curious. One night I started reading about dynos and thought it would be fun to build a simple simulator and see if an LLM could generate useful tuning suggestions from the results.

It turned into a small weekend project, so I decided to put it on GitHub.
