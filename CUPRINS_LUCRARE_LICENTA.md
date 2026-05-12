# Cuprinsul Lucrării de Diplomă/Licență

**Titlul lucrării:** 
*Orchestrare CI/CD Orientată pe Evenimente: Fuziune Speculativă, Pipeline-uri Dependente și Abstractizarea Configurației*

---

## Cuprins

Capitolul 1 Introducere (Memoriu Tehnico-Justificativ) .................................................... 5
1.1 Context și motivația alegerii temei ....................................................................... 7
1.2 Obiectivele generale ale lucrării .......................................................................... 8
1.3 Relevanța științifică și gradul de noutate ............................................................. 9
1.4 Strategia cercetării și metodologia folosită ............................................................ 10
1.5 Instrumente și infrastructură ................................................................................. 11
1.6 Limitele și delimitările lucrării .............................................................................. 12

Capitolul 2 Stadiul Actual și Fundamentele Teoretice ale Sistemelor CI/CD ........... 13
2.1 Deficiențe și limitări în platformele tradiționale de integrare ................................ 13
2.2 Platformele predominante pe piață ....................................................................... 14
2.2.1 Jenkins ....................................................................................................... 15
2.2.2 GitLab CI/CD ............................................................................................... 16
2.2.3 GitHub Actions ............................................................................................. 17
2.3 Paradigma sistemelor distribuite de evaluare a codului via Gerrit ........................... 18
2.4 Arhitecturi orientate pe evenimente (Event-Driven) ............................................... 19
2.4.1 Caracteristicile și beneficiile arhitecturilor event-driven .................................. 19
2.4.2 Brokerajul de mesaje prin Apache Kafka ...................................................... 21
2.5 Fuziuni speculative și stări predicate în VCS ......................................................... 22

Capitolul 3 Arhitectura Globală a Sistemului Torii: Infrastructură și Abstracție .... 25
3.1 Topologia microserviciilor și orchestrarea containerizată ....................................... 25
3.1.1 Decompoziția funcțională în module .............................................................. 26
3.1.2 Comunicația inter-servicii ............................................................................ 27
3.2 Ciclul de viață al unui eveniment din Gerrit ....................................................... 29
3.2.1 Ingestia și normalizarea fluxurilor de date .................................................... 30
3.2.2 Rutarea și prioritizarea evenimentelor ............................................................ 31
3.3 Paradigma "Configuration as Code" ................................................................... 32
3.3.1 Definiția și avantajele abstractizării declarative ............................................ 32
3.3.2 Structura fișierelor YAML (jobs.yaml, pipelines.yaml, projects.yaml) ............... 34

Capitolul 4 Gestionarea Modificărilor și Evaluarea Stărilor Speculative ................ 37
(Modulul Git Merger)
4.1 Conceptul de integrare speculativă ..................................................................... 37
4.1.1 Definirea stărilor speculative și a matricei de testare ..................................... 38
4.1.2 Abstractizarea operațiunilor de versionare ..................................................... 39
4.2 Implementarea Git Merger ................................................................................... 41
4.2.1 Arhitectura internă a modulului merger .......................................................... 41
4.2.2 Operații atomice de fuziune și ștergere ......................................................... 42
4.2.3 Gestionarea conflictelor și racei conditions .................................................... 44
4.3 Asigurarea proprietății de invarianță a stării (State Hygiene) ................................ 45
4.3.1 Mecanisme de GC și restricționarea leak-urilor de resurse .............................. 45
4.3.2 Validarea integrității repository-urilor ............................................................. 46
4.4 Topologii de flux (Pipeline Managers) ................................................................ 48
4.4.1 Evaluare independentă vs. secvențializată dependent .................................... 48
4.4.2 Algoritmi de ordonare și rezolvare a dependențelor ........................................ 50

Capitolul 5 Planificarea și Distribuția Sarcinilor (Modulul Scheduler) .................... 53
5.1 Modelarea matematică a job-urilor ....................................................................... 53
5.1.1 Reprezentarea abstractă a taskurilor și resurselor .......................................... 54
5.1.2 Modelul de cost și estimare a timpilor de execuție .......................................... 56
5.2 Alocarea și prioritizarea resurselor ..................................................................... 57
5.2.1 Strategii de mediere a resurselor .................................................................. 57
5.2.2 Algoritmi de fair-sharing și prevenirea starvation .......................................... 59
5.3 Prelucrarea cererilor concurente ........................................................................ 61
5.3.1 Structuri de cozi și buffer management .......................................................... 61
5.3.2 Implementarea pool-urilor de workers ............................................................ 62

Capitolul 6 Subsistemul Izolat de Execuție (Worker / Executor) ............................ 65
6.1 Principiile izolării spațiului de execuție ................................................................ 65
6.1.1 Containerizarea și sandbox-urile de execuție .................................................. 65
6.1.2 Injectarea dinamică a contextului de testare .................................................. 67
6.2 Captarea și procesarea log-urilor ....................................................................... 68
6.2.1 Transmisiunea în flux a jurnalelor de execuție (Log streaming) ....................... 68
6.2.2 Agregarea și indexarea log-urilor .................................................................. 70
6.3 Sincronizarea bidirecțională a statusului ............................................................. 71
6.3.1 Protocoale de comunicare și heartbeat mechanisms ....................................... 71
6.3.2 Notificări în timp real și feed-back loops ....................................................... 72

Capitolul 7 Componenta de Vizualizare și Sincronizare (Platforma Web UI) ......... 75
7.1 Arhitectura frontend și decuplarea nivelului de prezentare .................................... 75
7.1.1 Componentele React și componentizația ......................................................... 76
7.1.2 State management și reactivitate ................................................................... 77
7.2 Integrationarea cu backend și polling/socket logic ................................................ 79
7.2.1 Construirea dashboard-ului de status ............................................................. 79
7.2.2 Vizualizarea pipeline-urilor și fluxului de lucru ................................................ 81
7.3 Trasabilitatea și maparea stării în timp real ......................................................... 82
7.3.1 Implementarea flame graphs pentru fluxuri de lucru ........................................ 82
7.3.2 Sistem de notificări și alerting ..................................................................... 84

Capitolul 8 Evaluarea Performanțelor și Validarea Arhitecturii .............................. 85
8.1 Scenarii de testare izolate .................................................................................. 85
8.1.1 Evaluarea modificărilor unitare și cazuri de testare minimale .......................... 86
8.1.2 Validation framework și automatizare testelor ................................................. 87
8.2 Scenarii de testare la sarcină constantă .............................................................. 89
8.2.1 Validarea porților de integrare și a cozilor dependente ................................... 89
8.2.2 Teste de stress și teste de capacitate ............................................................ 91
8.3 Analiza consumului de resurse și latențelor de rețea ............................................ 92
8.3.1 Metricile de performanță și KPI-uri .............................................................. 92
8.3.2 Construirea modelelor de predicție și optimizare ............................................. 94

Capitolul 9 Concluzii, Contribuții și Direcții Viitoare de Cercetare ........................ 97
9.1 Concluzii generale ............................................................................................... 97
9.2 Contribuții aduse la starea artei ........................................................................... 99
9.3 Limitări ale soluției propuse ................................................................................ 100
9.4 Direcții viitoare de cercetare și extindere ............................................................. 102

Bibliografie ................................................................................................................ 105

---

## Listă Figuri

Figura 3.1: Topologia microserviciilor în Torii ............................................................. 26
Figura 3.2: Ciclul de viață al unui eveniment Gerrit ................................................... 29
Figura 3.3: Structura fișierelor de configurație YAML ................................................. 34
Figura 4.1: Diagrama stărilor speculative și a matricei de testare ............................... 38
Figura 4.2: Arhitectura internă a modulului Git Merger ............................................. 41
Figura 4.3: Exemple de topologii de pipeline (secvențial vs. paralel) .......................... 48
Figura 4.4: Graficul dependențelor între joburi .......................................................... 50
Figura 5.1: Alocarea resurselor și prioritizarea taskurilor ......................................... 57
Figura 5.2: Model de fair-sharing în scheduler .......................................................... 59
Figura 5.3: Gestionarea cozilor de așteptare ............................................................. 61
Figura 6.1: Arhitectura executorului izolat ................................................................ 65
Figura 6.2: Pipeline de procesare a log-urilor ........................................................... 68
Figura 6.3: Mecanismul de sincronizare bidirecțional ............................................... 71
Figura 7.1: Componentele principale ale UI-ului React ............................................... 76
Figura 7.2: Dashboard de status și monitorizare ......................................................... 79
Figura 7.3: Flame graph al execuției pipeline-urilor .................................................. 82
Figura 8.1: Rezultatele testelor de performanță ......................................................... 92
Figura 8.2: Analiza latențelor și consumului de resurse .............................................. 94

---

## Listă Tabele

Tabelul 3.1: Componente principale ale sistemului Torii și responsabilități ............... 27
Tabelul 4.1: Comparație între fuziuni speculative și fuziuni tradiționale ..................... 39
Tabelul 5.1: Parametrii modelului matematic de job scheduling .................................. 54
Tabelul 6.1: Protocoale de comunicare și mensaje interchange .................................. 71
Tabelul 8.1: Metricile de evaluare a performanței ..................................................... 92
Tabelul 8.2: Rezultatele testelor de stress ................................................................ 91

