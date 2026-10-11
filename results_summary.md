# Results summary (auto generated)

Model: Qwen/Qwen2.5-3B-Instruct, greedy decoding. Canvas 3100 x 2900. 40 schemas.

## Round 0: share of valid JSON layouts, by size

```
n_tables
5     1.0
8     1.0
12    0.9
16    0.8
```

## Round 0: failure types

```
n_tables  error       
12        invalid_json    1
16        invalid_json    2
```

## Average layout problems (overlaps + crossings + lines through tables)

```
          graphviz_neato  graphviz_dot  random  qwen_round0
n_tables                                                   
5                    0.5           1.6    2.08         5.90
8                    0.9           3.4    9.16        23.10
12                   2.6           8.1   25.16        54.78
16                   3.9           9.8   51.92        79.88
```

## Problems per foreign key

```
          graphviz_neato  random  qwen_round0
n_tables                                     
5                   0.08    0.35         0.98
8                   0.09    0.92         2.31
12                  0.16    1.57         3.42
16                  0.19    2.47         3.80
```

## Round 0 problem breakdown for Qwen, by size

```
          overlaps  crossings  through  out_of_bounds  total
n_tables                                                    
5             0.40       0.90     4.60           0.00   5.90
8             1.30       9.00    12.80           0.00  23.10
12            2.56      24.56    27.67           0.00  54.78
16            2.38      32.75    44.75           0.12  79.88
```

## Round 0 spread of positions (distinct x and y values)

```
          distinct_x  distinct_y
n_tables                        
5                4.1         3.1
8                3.4         5.0
12               6.0         7.7
16               6.9         5.6
```

## Average problems by round, condition: plain (schemas valid in every round)

```
round        0     1     2     3
n_tables                        
5          5.9   5.9   5.9   5.9
8         23.1  23.1  21.7  23.1
12        54.8  54.8  54.8  54.8
16        97.2  97.2  97.2  97.2
```

## Share of valid JSON by round, condition: plain

```
round       0    1    2    3
n_tables                    
5         1.0  1.0  1.0  1.0
8         1.0  1.0  1.0  1.0
12        0.9  1.0  1.0  1.0
16        0.8  0.5  0.5  0.5
```

## Average problems by round, condition: feedback (schemas valid in every round)

```
round        0     1     2     3
n_tables                        
5          5.9   4.7   6.3   4.4
8         23.1  18.5  19.2  19.2
12        54.8  41.6  47.7  45.7
16        79.9  76.6  77.1  73.5
```

## Share of valid JSON by round, condition: feedback

```
round       0    1    2    3
n_tables                    
5         1.0  1.0  1.0  1.0
8         1.0  1.0  1.0  1.0
12        0.9  1.0  1.0  1.0
16        0.8  0.8  0.8  0.8
```

## Repair regression: did a round make the layout worse?

```
condition  round  n  worse_%  same_%  better_%  mean_change
    plain      1 34      0.0   100.0       0.0         0.00
    plain      2 35      0.0    94.3       5.7        -0.40
    plain      3 35      5.7    94.3       0.0         0.40
    plain 0 to 3 34      0.0   100.0       0.0         0.00
 feedback      1 37     10.8    32.4      56.8        -5.49
 feedback      2 38     23.7    71.1       5.3         2.16
 feedback      3 38      7.9    68.4      23.7        -1.74
 feedback 0 to 3 37     10.8    32.4      56.8        -5.05
```
