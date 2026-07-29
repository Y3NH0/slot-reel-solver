## Generate any valid Slot Game reel configuration that meets the following requirements

### Rules

1. The RTP (Return to Player) must be 0.95.  
   (Assume a total bet amount of 100 units; the expected return for the user per 100 units bet should be 95 units.)
2. The user’s win rate must not be lower than 55%.
3. The slot game display consists of 3 columns × 3 rows.
4. There are five winning patterns, as shown below (the blocks (■) must all be the same symbol to trigger a win):

   #### Winning Patterns ####
   4.1.
     | ■ | ■ |   |
     |---|---|---|
     | ■ | ■ |   |
     |---|---|---|
     |   |   |   |
   
   4.2. 
     |   | ■ | ■ |
     |---|---|---|
     |   | ■ | ■ |
     |---|---|---|
     |   |   |   |
   
   4.3.
     |   |   |   |
     |---|---|---|
     | ■ | ■ |   |
     |---|---|---|
     | ■ | ■ |   |
   
   4.4. 
     |   |   |   |
     |---|---|---|
     |   | ■ | ■ |
     |---|---|---|
     |   | ■ | ■ |
   
   4.5. 
     | ■ | ■ | ■ |
     |---|---|---|
     | ■ | ■ | ■ |
     |---|---|---|
     | ■ | ■ | ■ |
   #### Winning Patterns ####
     
5. For the first four patterns, the payout is: **bet amount × symbol multiplier**.  
   For the fifth pattern, the payout is: **bet amount × symbol multiplier × 5**.
6. There are **5 types of symbols**. Their keys and multipliers are as follows:  
   `{0: 0.25, 1: 0.55, 2: 1, 3: 3, 4: 5}`
7. The reels do **not** need to be of equal length, nor is there any limit on their lengths.  
   You can imagine them as being placed on large, possibly uneven, rotating drums.

