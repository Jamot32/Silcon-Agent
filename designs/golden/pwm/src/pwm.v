`default_nettype none

module pwm #(
    parameter PERIOD = 256
) (
    input wire clk,
    input wire rst_n,
    input wire [7:0] duty,
    output reg pwm_out
);
    localparam [7:0] LAST_PHASE = PERIOD[7:0] - 8'd1;
    reg [7:0] phase;

    always @(posedge clk) begin
        if (!rst_n) begin
            phase <= 8'd0;
            pwm_out <= 1'b0;
        end else begin
            pwm_out <= (phase < duty);
            if (phase == LAST_PHASE)
                phase <= 8'd0;
            else
                phase <= phase + 8'd1;
        end
    end
endmodule

`default_nettype wire
