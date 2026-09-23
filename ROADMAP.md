<!-- serves: J1, J3, J4 -->
# RailBlock AI — Technical Roadmap (Tier C / Future Work)

This document outlines future architectural extensions explicitly deferred from the immediate Smart India Hackathon prototype scope.

## 1. Multi-Objective Genetic Algorithm Layer (NSGA-II)
- **Concept**: Evolutionary search layer (NSGA-II) operating on top of CP-SAT + RL outputs to generate a Pareto front of weekly schedules balancing asset availability, maintenance cost, and delay risk.
- **Status**: Deferred. The hybrid CP-SAT batch + Offline RL reactive dispatcher provides exact optimal baseline and millisecond response times without non-deterministic GA overhead.

## 2. Live Production Integration with IR Legacy Systems
- **Concept**: Direct REST/SOAP/Kafka connectivity to production instances of BDMS, COA, TMS, SMMS, and TDMS.
- **Status**: Deferred. Implemented as high-fidelity adapter interfaces (`backend/adapters/`) with mock data providers and documented schema payloads.

## 3. Field Worker Mobile App for Defect & Block Sign-off
- **Concept**: Mobile application for PWI, OWD, and S&T supervisors to report real-time defect logs, record block start/end times, and submit geotagged completion proof.
- **Status**: Deferred. Simulated via the REST `/api/tasks/demand` injection interface and TrackStatus FSM transition endpoints.

## 4. IoT & Computer Vision Automated Defect Detection Integration
- **Concept**: Ingestion of track geometry car streams, acoustic bearing sensors, and trackside CV camera alerts directly into the task pool.
- **Status**: Deferred. Simulated via stochastic DEMAND task generation.

## 5. Federated Multi-Division & National Rollout Architecture
- **Concept**: Multi-node federated RL training across Indian Railways divisions and zones (Central Railway, Western Railway, Northern Railway) with localized constraint parameters.
- **Status**: Deferred. Proven architecturally via YAML corridor configuration (`config/network/`).

## 6. Microscopic Signalling Digital Twin
- **Concept**: Interlocking-level signal and aspect microsimulation (e.g. 4-aspect automatic block signaling clearance verification).
- **Status**: Deferred. Macro-level section occupancy interval-tree gap engine provides exact safety headway enforcement (120s buffer).
