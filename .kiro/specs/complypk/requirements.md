# Requirements Document

## Introduction

ComplyPK is an open-source cyber-security readiness assessment web application targeted at Pakistani SMEs and fintechs. A user answers a fixed questionnaire of 20 yes/partial/no questions grouped into security domains. The application scores the responses overall and per domain, maps failed items to ISO 27001 and NIST CSF controls, identifies gaps with severity, and produces a prioritized remediation plan (LLM-generated with a template-based fallback). Assessments are persisted so users can view history, retrieve a single assessment, and export a report. A demo mode preloads a sample fintech company's answers.

The product is a **readiness assessment** tool only. It does not provide certification, guaranteed compliance, or any legal assurance. Every assessment output includes a disclaimer stating this.

This is a solo-developer, 2-day hackathon project. The architecture is intentionally layered and cleanly separated (backend/frontend) with best practices prioritized over feature count: Python 3.11 + FastAPI + SQLAlchemy + Pydantic on the backend (routers → services → repositories → models), SQLite locally / PostgreSQL in production, and a simple responsive web frontend calling the REST API. Secrets are never committed; all configuration flows through environment variables.

### Out of Scope

- User authentication and authorization
- Payments or billing
- Real network scanning or automated vulnerability detection
- Multi-language support
- Administrative dashboards

## Glossary

- **ComplyPK**: The overall application, comprising the Backend and Frontend.
- **Backend_API**: The FastAPI REST service exposing endpoints for questionnaires, assessments, remediation, export, and demo mode.
- **Frontend_App**: The responsive web client (React + Vite or HTML/JS + Tailwind) that calls the Backend_API.
- **Questionnaire**: The fixed set of 20 questions loaded from a JSON file, grouped into Domains.
- **Question**: A single questionnaire item answered with one of the Answer_Values.
- **Answer_Value**: One of "yes", "partial", or "no".
- **Domain**: A security category. The six Domains are Access Control, Backup & Recovery, Patching, Incident Response, Vendor Risk, and Data Protection.
- **Assessment**: A completed set of answers plus its computed Overall_Score, Domain_Scores, Gaps, and metadata, persisted in the Database.
- **Overall_Score**: A numeric readiness score (0-100) computed across all answers.
- **Domain_Score**: A numeric readiness score (0-100) computed for one Domain.
- **Gap**: A failed or partially satisfied Question, including its Severity and mapped controls.
- **Severity**: One of "low", "medium", or "high", indicating the risk level of a Gap.
- **Control_Mapping**: An editable JSON file associating Questions with ISO 27001 and NIST CSF controls.
- **ISO_27001**: The ISO/IEC 27001 information security management standard referenced by the Control_Mapping.
- **NIST_CSF**: The NIST Cybersecurity Framework referenced by the Control_Mapping.
- **Remediation_Plan**: A prioritized list of recommended steps that address the Gaps of an Assessment.
- **LLM_Service**: The component that generates a Remediation_Plan using an external large language model API.
- **Fallback_Generator**: The component that produces a template-based Remediation_Plan when the LLM_Service is unavailable or fails.
- **Report**: An exportable document (Markdown or PDF) containing the Overall_Score, Domain_Scores, Gaps, Control_Mapping references, Remediation_Plan, and Disclaimer.
- **Disclaimer**: A fixed statement clarifying that ComplyPK provides a readiness assessment only and does not provide certification or guaranteed compliance.
- **Demo_Mode**: A feature that supplies a sample fintech company's prefilled answers.
- **Database**: The persistence layer, SQLite locally and PostgreSQL in production, selected via the DATABASE_URL environment variable.
- **DATABASE_URL**: The environment variable specifying the Database connection string.
- **LLM_API_KEY**: The environment variable holding the credential used by the LLM_Service.
- **Environment_Configuration**: The set of environment variables (including DATABASE_URL, LLM_API_KEY, and the allowed frontend origin) used to configure ComplyPK.

## Requirements

### Requirement 1: Retrieve Questionnaire

**User Story:** As an SME owner, I want to retrieve the readiness questionnaire grouped by security domain, so that I can understand and answer the assessment questions.

#### Acceptance Criteria

1. WHEN a client requests the questionnaire, THE Backend_API SHALL load the Questionnaire from the JSON file and return exactly 20 Questions within 2 seconds.
2. WHEN the Backend_API returns the Questionnaire, THE Backend_API SHALL group the Questions under the six Domains: Access Control, Backup & Recovery, Patching, Incident Response, Vendor Risk, and Data Protection.
3. WHEN the Backend_API returns a Question, THE Backend_API SHALL include the Question identifier, the Question text, the owning Domain, and the three permitted Answer_Values ("yes", "partial", "no").
4. IF the Questionnaire JSON file is missing or cannot be parsed, THEN THE Backend_API SHALL return an HTTP 500 response with an error indication that the questionnaire could not be loaded, SHALL NOT expose internal stack traces, and SHALL NOT return partial Questionnaire data.
5. IF the loaded Questionnaire does not contain exactly 20 Questions, or any Question is missing its identifier, text, owning Domain, or three Answer_Values ("yes", "partial", "no"), THEN THE Backend_API SHALL return an HTTP 500 response with an error indication that the questionnaire data is invalid and SHALL NOT return partial Questionnaire data.

### Requirement 2: Submit Assessment and Compute Scores

**User Story:** As an SME owner, I want to submit my answers and receive overall and per-domain readiness scores, so that I can see where my organization stands.

#### Acceptance Criteria

1. WHEN a client submits a complete set of answers for all 20 Questions, THE Backend_API SHALL compute the Overall_Score as the sum of all answer weights divided by 20, multiplied by 100, and rounded to the nearest integer, producing a value between 0 and 100.
2. WHEN the Backend_API computes scores, THE Backend_API SHALL compute, for each of the six Domains (Access Control, Backup & Recovery, Patching, Incident Response, Vendor Risk, and Data Protection), a Domain_Score as the sum of that Domain's answer weights divided by that Domain's Question count, multiplied by 100, and rounded to the nearest integer, producing a value between 0 and 100.
3. WHEN the Backend_API computes a score, THE Backend_API SHALL assign an answer weight of 1.0 to an Answer_Value of "yes", 0.5 to "partial", and 0.0 to "no".
4. WHEN a submission passes validation and scoring completes, THE Backend_API SHALL persist the Assessment, including its answers, Overall_Score, Domain_Scores, Gaps, and a creation timestamp, to the Database.
5. WHEN the Backend_API persists an Assessment, THE Backend_API SHALL return the stored Assessment including its unique identifier.
6. IF a submission omits any of the 20 Questions, or contains an answer whose Answer_Value is not one of "yes", "partial", or "no", THEN THE Backend_API SHALL return an HTTP 422 response identifying the missing Question identifiers and invalid Answer_Values, and SHALL NOT persist any part of the Assessment to the Database regardless of whether scores were computed.

### Requirement 3: Map Gaps to Controls with Severity

**User Story:** As a compliance-conscious fintech operator, I want failed items mapped to ISO 27001 and NIST CSF controls with a severity, so that I know which standards each gap relates to and how urgent it is.

#### Acceptance Criteria

1. WHEN the Backend_API computes an Assessment, THE Backend_API SHALL classify every Question whose Answer_Value is "no" or "partial" as a Gap, and SHALL NOT classify any Question whose Answer_Value is "yes" as a Gap.
2. WHEN the Backend_API produces a Gap, THE Backend_API SHALL attach the ISO_27001 and NIST_CSF control references defined for that Question in the Control_Mapping JSON file, using an empty reference list for a standard that has no reference defined for that Question.
3. WHEN the Backend_API produces a Gap, THE Backend_API SHALL assign a Severity of exactly one of "low", "medium", or "high", assigning "high" to a Gap whose Answer_Value is "no" and "medium" to a Gap whose Answer_Value is "partial".
4. THE Backend_API SHALL read all control associations from the editable Control_Mapping JSON file and SHALL NOT read them from hard-coded values.
5. IF a Question has no entry in the Control_Mapping JSON file, THEN THE Backend_API SHALL produce the Gap with empty ISO_27001 and NIST_CSF control reference lists, SHALL assign its Severity using the rule in criterion 3, and SHALL continue processing the remaining Gaps.
6. IF the Control_Mapping JSON file is missing or cannot be parsed, THEN THE Backend_API SHALL return an HTTP 500 response with a descriptive error message, SHALL NOT expose internal stack traces, and SHALL NOT persist a partially mapped Assessment.

### Requirement 4: Retrieve Assessment History and Single Assessment

**User Story:** As a returning user, I want to view my past assessments and open any single assessment, so that I can track progress over time.

#### Acceptance Criteria

1. WHEN a client requests the assessment history, THE Backend_API SHALL return a list of stored Assessments ordered by creation timestamp from most recent to least recent, and SHALL order any Assessments sharing the same creation timestamp by descending identifier.
2. WHEN a client requests a single Assessment by its identifier, THE Backend_API SHALL return that Assessment including its identifier, creation timestamp, Overall_Score, Domain_Scores, and Gaps.
3. IF a client requests an Assessment whose identifier does not exist in the Database, THEN THE Backend_API SHALL return an HTTP 404 response with a descriptive error message and SHALL NOT return any Assessment data.
4. WHEN a client requests the assessment history and no Assessments are stored in the Database, THE Backend_API SHALL return an HTTP 200 response containing an empty list.
5. WHEN a client requests the assessment history, THE Backend_API SHALL include for each listed Assessment its identifier, creation timestamp, and Overall_Score.
6. IF a client requests a single Assessment using an identifier whose type or format is invalid, THEN THE Backend_API SHALL return an HTTP 422 response with a descriptive error message and SHALL NOT return any Assessment data.

### Requirement 5: Generate Remediation Plan with Fallback

**User Story:** As an SME owner, I want a prioritized remediation plan for my gaps, so that I know what to fix first even if the AI service is unavailable.

#### Acceptance Criteria

1. WHEN a client requests a Remediation_Plan for an existing Assessment, THE LLM_Service SHALL generate a list of remediation steps prioritized by Gap Severity using the external LLM API identified by LLM_API_KEY, subject to a maximum wait of 30 seconds.
2. WHEN the Backend_API returns a Remediation_Plan, THE Backend_API SHALL order the steps so that steps addressing higher-Severity Gaps appear before steps addressing lower-Severity Gaps, and SHALL order steps addressing Gaps of equal Severity by ascending Question identifier.
3. WHEN the Backend_API returns a Remediation_Plan, THE Backend_API SHALL include at least one remediation step for each Gap in the Assessment.
4. IF the LLM_API_KEY environment variable is not set, THEN THE Fallback_Generator SHALL produce a template-based Remediation_Plan derived from the Gaps.
5. IF the external LLM API call fails or does not respond within 30 seconds, THEN THE Fallback_Generator SHALL produce a template-based Remediation_Plan and THE Backend_API SHALL return an HTTP 200 response.
6. WHEN the Backend_API returns a Remediation_Plan, THE Backend_API SHALL indicate whether the plan was generated by the LLM_Service or the Fallback_Generator.
7. IF a client requests a Remediation_Plan for an Assessment identifier that does not exist, THEN THE Backend_API SHALL return an HTTP 404 response with a descriptive error message.

### Requirement 6: Export Report

**User Story:** As a fintech operator, I want to export a report of my assessment, so that I can share results with my team or stakeholders.

#### Acceptance Criteria

1. WHEN a client requests a Report export for an existing Assessment and specifies a Report format of "markdown" or "pdf", THE Backend_API SHALL produce a Report in the specified format within 10 seconds.
2. WHEN a client requests a Report export for an existing Assessment without specifying a format, THE Backend_API SHALL produce a Report in Markdown format.
3. WHEN the Backend_API produces a Report, THE Backend_API SHALL include the Overall_Score, the Domain_Score for each of the six Domains, every Gap with its Severity, the ISO_27001 and NIST_CSF control references for each Gap, and the Remediation_Plan.
4. WHEN the Backend_API produces a Report for an Assessment that has no generated Remediation_Plan, THE Backend_API SHALL include every other required section and SHALL indicate in the Remediation_Plan section that no Remediation_Plan has been generated.
5. WHEN the Backend_API produces a Report, THE Backend_API SHALL include the Disclaimer text in the Report.
6. IF a client requests a Report for an Assessment identifier that does not exist, THEN THE Backend_API SHALL return an HTTP 404 response with a descriptive error message.
7. IF a client requests a Report format other than "markdown" or "pdf", THEN THE Backend_API SHALL return an HTTP 422 response identifying the invalid format and SHALL NOT produce a Report.

### Requirement 7: Demo Mode

**User Story:** As a judge or first-time visitor, I want a demo mode with a sample fintech company, so that I can see a full assessment without entering data.

#### Acceptance Criteria

1. WHEN a client requests Demo_Mode, THE Backend_API SHALL return a sample fintech company profile together with exactly one valid Answer_Value ("yes", "partial", or "no") for each of the 20 Questions.
2. WHILE the Questionnaire is loaded and Demo_Mode data is provided, THE Frontend_App SHALL populate the questionnaire with the prefilled answers.
3. WHEN the questionnaire is populated with Demo_Mode answers, THE Frontend_App SHALL allow the user to submit the prefilled answers as an Assessment.
4. THE Backend_API SHALL source Demo_Mode answers from fixed sample data rather than from real customer records.
5. IF the Demo_Mode sample data is missing or invalid, THEN THE Backend_API SHALL return an HTTP 500 response with a descriptive error message and SHALL NOT return partial Demo_Mode data.

### Requirement 8: Readiness-Only Wording and Disclaimer

**User Story:** As a compliance-conscious user, I want clear wording that this is a readiness assessment and not certification, so that I do not misrepresent my compliance status.

#### Acceptance Criteria

1. THE ComplyPK SHALL describe its output as a "readiness assessment" in all user-facing Assessment results and Reports, and SHALL NOT use the terms "certification", "certified", "guaranteed compliance", or "compliant" to describe its output in any user-facing Assessment result or Report.
2. WHEN the Frontend_App displays Assessment results, THE Frontend_App SHALL display the Disclaimer on the same view as the results without requiring further user interaction, where the Disclaimer states that ComplyPK provides a readiness assessment only and does not constitute certification or a guarantee of compliance.
3. WHEN the Backend_API produces a Report, THE Backend_API SHALL include the Disclaimer in the Report, where the Disclaimer states that ComplyPK provides a readiness assessment only and does not constitute certification or a guarantee of compliance.
4. IF the Backend_API cannot include the Disclaimer in a Report, THEN THE Backend_API SHALL NOT produce the Report and SHALL return an error response indicating that the Report could not be generated without the Disclaimer.

### Requirement 9: Secrets Safety and Environment Configuration

**User Story:** As the developer, I want all secrets and environment-specific settings loaded from environment variables with nothing sensitive committed, so that the project is safe to open-source and deploy.

#### Acceptance Criteria

1. WHEN the Backend_API starts, THE Backend_API SHALL read DATABASE_URL, LLM_API_KEY, and the allowed frontend origin from the Environment_Configuration.
2. WHERE DATABASE_URL is not set, THE Backend_API SHALL default to a local SQLite Database.
3. WHERE DATABASE_URL specifies a PostgreSQL connection, THE Backend_API SHALL use PostgreSQL as the Database.
4. IF the allowed frontend origin is not set when the Backend_API starts, THEN THE Backend_API SHALL fail to start with an error message identifying the missing configuration and SHALL NOT serve requests.
5. IF DATABASE_URL is set but malformed, THEN THE Backend_API SHALL fail to start with an error message identifying the invalid configuration and SHALL NOT expose the DATABASE_URL value in that message.
6. THE repository SHALL include an `.env.example` file documenting required environment variables without real values.
7. THE repository SHALL include a `.gitignore` entry that excludes the `.env` file and other secret-bearing files from version control.
8. THE Backend_API SHALL NOT include secret values in API responses, logs, or error messages.

### Requirement 10: API Input Validation

**User Story:** As the developer, I want all API inputs validated, so that malformed requests are rejected cleanly and the service stays robust.

#### Acceptance Criteria

1. WHEN the Backend_API receives a request body, THE Backend_API SHALL validate the body against a Pydantic schema before performing any processing or persistence.
2. IF a request body fails schema validation, THEN THE Backend_API SHALL return an HTTP 422 response identifying the offending fields using the consistent JSON error structure and SHALL NOT process or persist the request.
3. IF a path or query parameter has an invalid type or format, THEN THE Backend_API SHALL return an HTTP 422 response with a descriptive error message using the consistent JSON error structure.
4. WHEN the Backend_API receives an answer submission, THE Backend_API SHALL return an HTTP 422 response identifying any answer whose Question identifier is not part of the Questionnaire and SHALL NOT persist the submission.
5. IF a request body is not well-formed JSON or is empty when a body is required, THEN THE Backend_API SHALL return an HTTP 422 response with a descriptive error message and SHALL NOT process the request.
6. IF a request body exceeds the maximum accepted size, THEN THE Backend_API SHALL reject the request with an HTTP 413 response and SHALL NOT process the request.

### Requirement 11: Error Handling

**User Story:** As a user, I want consistent and safe error responses, so that failures are understandable and do not leak internal details.

#### Acceptance Criteria

1. IF an unhandled error occurs while processing a request, THEN THE Backend_API SHALL return an HTTP 500 response with a generic error message and SHALL NOT expose internal stack traces, file paths, or secret values.
2. WHEN the Backend_API returns an error response, THE Backend_API SHALL use a consistent JSON error structure containing a human-readable message field and a unique error reference identifier.
3. IF the Backend_API cannot establish a Database connection within 5 seconds, THEN THE Backend_API SHALL return an HTTP 503 response indicating the service is temporarily unavailable and SHALL include a Retry-After value of no more than 30 seconds.
4. WHEN the Frontend_App receives an error response from the Backend_API, THE Frontend_App SHALL display a user-facing error message within 1 second of receiving the response.
5. WHILE an error message is displayed, THE Frontend_App SHALL keep navigation controls and form inputs interactive and SHALL allow the user to retry the failed action without reloading the page.
6. IF the Frontend_App does not receive a response from the Backend_API within 30 seconds of sending a request, THEN THE Frontend_App SHALL cancel the request and display a user-facing timeout error message while remaining interactive.

### Requirement 12: Layered Architecture and Separation

**User Story:** As a maintainer and judge, I want a cleanly layered, deployable full-stack project, so that the code is readable, testable, and follows best practices.

#### Acceptance Criteria

1. THE ComplyPK SHALL organize source code into separate `/backend` and `/frontend` folders.
2. THE Backend_API SHALL separate responsibilities into routers, services, repositories, and models layers such that routers depend only on services, services depend only on repositories, and repositories depend only on models, with no dependencies in the reverse direction.
3. THE Backend_API SHALL define all request and response data structures using Pydantic schemas.
4. WHEN the Backend_API receives a cross-origin request whose origin matches the allowed frontend origin defined in the Environment_Configuration, THE Backend_API SHALL permit the request.
5. IF the Backend_API receives a cross-origin request whose origin does not match the allowed frontend origin defined in the Environment_Configuration, THEN THE Backend_API SHALL omit the cross-origin access headers so that the browser blocks the response.
6. THE repository SHALL include automated pytest tests covering scoring, Gap mapping, and Fallback_Generator behavior, and all included tests SHALL pass when executed.
7. THE repository SHALL include either a Dockerfile for the Backend_API or documented step-by-step run and deploy instructions sufficient to start the Backend_API, and SHALL include deployment notes describing how to build and serve the Frontend_App.
